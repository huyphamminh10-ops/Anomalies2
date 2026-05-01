import disnake
from roles.base_role import BaseRole

class TheNeuroParasite(BaseRole):
    name = "Ký Sinh Thần Kinh"
    team = "Anomalies"
    max_count = 1

    description = (
        "Bạn là Ký Sinh Trùng — một thực thể có khả năng tha hóa tâm trí người khác.\n\n"
        "• Mỗi đêm, bạn có thể chọn 1 người để ký sinh.\n"
        "• Quá trình tha hóa kéo dài 3 ngày. Sau 3 ngày, nạn nhân sẽ trở thành Anomaly.\n"
        "• Nếu vật chủ chết giữa chừng, quá trình thất bại và bạn có thể chọn mục tiêu mới vào đêm sau.\n"
        "• Ký sinh trong âm thầm — nạn nhân sẽ không biết mình bị ký sinh cho đến khi quá trình hoàn tất."
    )

    dm_message = (
        "🦠 **KÝ SINH THẦN KINH**\n\n"
        "Bạn thuộc phe **Dị Thể**.\n\n"
        "📖 **Lore:** Một sinh vật gớm ghiếc vô hình, có khả năng xâm nhập vào hệ thần kinh của những kẻ sống sót, từ từ ăn mòn ý lý và biến họ thành những con rối phục tùng phe Dị Thể.\n\n"
        "📋 **Cơ chế Kỹ Năng:**\n"
        "• Mỗi đêm, chọn 1 mục tiêu để ký sinh.\n"
        "• Cần 3 ngày (3 vòng ban ngày) để tha hóa hoàn toàn vật chủ.\n"
        "• Vật chủ sẽ bị biến thành Anomaly (hoặc Anomaly Servant) và mất role cũ.\n\n"
        "⚠ **Giới Hạn & Cân Bằng:**\n"
        "• Chỉ có thể ký sinh 1 người cùng lúc.\n"
        "• Không thể chọn đồng đội Dị Thể hoặc những người đã từng bị ký sinh trước đó.\n"
        "• Nếu vật chủ chết, bạn mất liên kết và có thể ký sinh người mới.\n"
        "• Nếu bạn chết, quá trình tha hóa đang diễn ra sẽ lập tức bị hủy bỏ."
    )

    def __init__(self, player):
        super().__init__(player)
        self.host_id = None
        self.days_infected = 0
        self.infected_history = set()  # Lưu những người đã từng bị ký sinh để không ký sinh lại

    async def on_game_start(self, game):
        """Thông báo danh sách đồng đội khi game bắt đầu."""
        import disnake
        teammates = [
            game.players[pid]
            for pid, role in game.roles.items()
            if getattr(role, 'team', '') == 'Anomalies' and pid != self.player.id
        ]
        if not teammates:
            return
        names = ', '.join('**' + m.display_name + '**' for m in teammates)
        desc = 'Đồng đội của bạn:' + chr(10) + names
        await self.safe_send(
            embed=disnake.Embed(
                title='👥 Đồng Đội Dị Thể',
                description=desc,
                color=0xe74c3c
            )
        )


    # =====================================
    # UI BAN ĐÊM - CHỌN MỤC TIÊU
    # =====================================
    async def send_ui(self, game):
        # Nếu đang có vật chủ và vật chủ còn sống, hiển thị tiến độ
        if self.host_id and game.is_alive(self.host_id):
            try:
                await self.safe_send(
                    embed=disnake.Embed(
                        title="🦠 ĐANG KÝ SINH",
                        description=f"Bạn đang trong quá trình tha hóa vật chủ.\nThời gian đã qua: **{self.days_infected}/3** ngày.",
                        color=0x9b59b6
                    )
                )
            except Exception:
                pass
            return

        # Lọc ra danh sách mục tiêu hợp lệ:
        # - Còn sống
        # - Không phải bản thân
        # - Chưa từng bị ký sinh
        # - Không thuộc phe Dị Thể
        alive = [
            p for p in game.get_alive_players()
            if p.id != self.player.id
            and p.id not in self.infected_history
            and game.roles.get(p.id)
            and game.roles[p.id].team != "Dị Thể"
        ]

        if not alive:
            return

        view = self.ParasiteView(game, self, alive)

        try:
            await self.safe_send(
                embed=disnake.Embed(
                    title="🦠 CHỌN MỤC TIÊU KÝ SINH",
                    description="Hãy chọn một nạn nhân để bắt đầu quá trình tha hóa:",
                    color=0x9b59b6
                ),
                view=view
            )
        except Exception:
            pass

    # =====================================
    # XỬ LÝ SỰ KIỆN QUA TỪNG NGÀY
    # =====================================
    async def on_day_start(self, game):
        """
        Hook này cần được gọi mỗi khi bắt đầu một ngày mới (hoặc vòng ban ngày mới).
        Thay đổi tên hook tương ứng với engine game của bạn (VD: on_phase_start).
        """
        if not self.host_id:
            return

        # Kiểm tra nếu Parasite đã chết -> Hủy quá trình
        if not game.is_alive(self.player.id):
            self.host_id = None
            self.days_infected = 0
            return

        # Kiểm tra nếu Vật Chủ chết -> Hủy quá trình để đêm tới ký sinh người mới
        if not game.is_alive(self.host_id):
            self.host_id = None
            self.days_infected = 0
            return

        # Tăng số ngày bị ký sinh
        self.days_infected += 1

        # Tha hóa thành công
        if self.days_infected >= 3:
            await self.complete_corruption(game)

    async def complete_corruption(self, game):
        host = game.players.get(self.host_id)
        if host:
            # 1. Biến vật chủ thành Anomaly (Nếu có role AnomalyServant riêng, bạn hãy import và dùng role đó)
            from roles.anomalies.anomaly import Anomaly
            new_role = Anomaly(host)
            game.roles[self.host_id] = new_role
            
            # Gỡ bỏ trạng thái vật chủ của Parasite
            self.host_id = None
            self.days_infected = 0
            
            # Gọi hook bắt đầu game của Anomaly để người bị biến đổi biết ai là đồng đội nếu cần thiết
            await new_role.on_game_start(game)

            # 2. Gửi thông báo cho nạn nhân bị tha hóa
            try:
                await host.send(
                    embed=disnake.Embed(
                        title="🔴 BẠN ĐÃ BỊ THA HÓA",
                        description="Bạn cảm thấy cơ thể mình bị biến đổi... Bạn đã trở thành một **Anomaly**.",
                        color=0xe74c3c
                    )
                )
            except Exception:
                pass
            
            # 3. Thông báo toàn hệ thống (Broadcast cho mọi người)
            if hasattr(game, "channel") and game.channel:
                try:
                    await game.channel.send(
                        embed=disnake.Embed(
                            title="⚠️ CẢNH BÁO",
                            description="Một thực thể đã tha hóa thành công một nạn nhân.",
                            color=0xe74c3c
                        )
                    )
                except Exception:
                    pass

    # =====================================
    # XỬ LÝ SỰ KIỆN KHI CÓ NGƯỜI CHẾT
    # =====================================
    async def on_player_death(self, game, dead_player_id):
        """
        Hook này gọi khi có một người chơi chết.
        Tùy theo engine, bạn có thể gọi từ game.queue_kill() hoặc tương tự.
        """
        if self.host_id is None:
            return

        # Nếu Parasite chết hoặc Host chết -> Hủy bỏ liên kết
        if dead_player_id == self.player.id or dead_player_id == self.host_id:
            self.host_id = None
            self.days_infected = 0

    # =====================================
    # VIEW
    # =====================================
    class ParasiteView(disnake.ui.View):
        def __init__(self, game, role, alive_list):
            super().__init__(timeout=60)
            options = [
                disnake.SelectOption(label=p.display_name, value=str(p.id))
                for p in alive_list
            ][:25]
            self.add_item(TheNeuroParasite.ParasiteSelect(game, role, options))

    class ParasiteSelect(disnake.ui.Select):
        def __init__(self, game, role, options):
            self.game = game
            self.role = role

            super().__init__(
                placeholder="Chọn mục tiêu ký sinh...",
                options=options[:25],
                min_values=1,
                max_values=1
            )

        async def callback(self, interaction: disnake.ApplicationCommandInteraction):
            if interaction.user.id != self.role.player.id:
                await interaction.response.send_message(
                    "Đây không phải lượt của bạn.",
                    ephemeral=True
                )
                return

            target_id = int(self.values[0])

            self.role.host_id = target_id
            self.role.days_infected = 0
            self.role.infected_history.add(target_id)

            await interaction.response.send_message(
                embed=disnake.Embed(
                    title="🦠 KÝ SINH THÀNH CÔNG",
                    description="Ký sinh đã bắt đầu lên mục tiêu.\nQuá trình tha hóa sẽ hoàn tất sau **3 ngày** nữa.",
                    color=0x9b59b6
                ),
                ephemeral=True
            )

            for item in self.view.children:
                item.disabled = True

            await interaction.message.edit(view=self.view)