class BaseRole:

    name        = "Base"
    faction     = "Không xác định"
    team        = "Không xác định"   # Dùng trong game engine (Survivors / Anomalies / Unknown)
    max_count   = 1
    description = "Không có mô tả"

    def __init__(self, player):
        self.player = player
        self.alive  = True

        # Đồng bộ faction ↔ team để tránh xung đột
        if self.team == "Không xác định" and self.faction != "Không xác định":
            self.team = self.faction
        elif self.faction == "Không xác định" and self.team != "Không xác định":
            self.faction = self.team

    async def safe_send(self, *args, **kwargs):
        """Wrapper an toàn cho self.player.send() — không crash nếu DM bị tắt."""
        try:
            return await self.player.send(*args, **kwargs)
        except Exception:
            pass

    async def night_action(self, game):
        pass

    async def day_action(self, game):
        pass

    async def on_death(self, game):
        """Hook gọi khi role này chết. Override ở subclass nếu cần."""
        pass

    async def on_game_start(self, game):
        """Hook gọi khi game bắt đầu. Override ở subclass nếu cần."""
        pass

    def vote_weight(self):
        """Hệ số phiếu bầu. Override nếu role có hệ số đặc biệt."""
        return 1

    def info_text(self):
        return (
            f"🎭 Vai trò: {self.name}\n"
            f"🏳️ Phe: {self.team}\n"
            f"📜 Mô tả: {self.description}"
        )
