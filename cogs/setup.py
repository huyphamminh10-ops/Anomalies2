import discord
import traceback
from discord.ext import commands
from discord import app_commands
from config_manager import load_guild_config, save_guild_config
from updater import greet_owner_on_setup
from cogs.settings import check_command_permission as _check_perm


class Setup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ===============================
    # HÀM PHỤ LẤY CATEGORY OBJECT
    # ===============================
    def lay_category(self, guild_id):
        config = load_guild_config(guild_id)
        category_id = config.get("category_id")

        if not category_id:
            return None

        try:
            channel = self.bot.get_channel(int(category_id))
        except (TypeError, ValueError):
            return None

        if isinstance(channel, discord.CategoryChannel):
            return channel

        return None

    # ===============================
    # HÀM PHỤ LẤY TÊN CATEGORY
    # ===============================
    def lay_ten_category(self, guild_id) -> str:
        category = self.lay_category(guild_id)
        return category.name if category else "Chưa đặt"

    # ===============================
    # LỆNH /setup
    # ===============================
    @app_commands.command(name="setup", description="Tạo hệ thống Anomalies cho server")
    @app_commands.guild_only()
    async def setup_command(self, interaction: discord.Interaction):

        guild = interaction.guild
        guild_id = str(guild.id)
        config = load_guild_config(guild_id)
        if not _check_perm(interaction, config):
            return await interaction.response.send_message(
                "❌ Bạn không có quyền sử dụng lệnh này.", ephemeral=True
            )

        # Gửi DM hướng dẫn update cho owner bot
        await greet_owner_on_setup(interaction)

        print(f"[SETUP] Bắt đầu setup cho server: {guild.name} ({guild.id})")

        try:
            config = load_guild_config(guild_id)

            # Nếu đã setup trước đó
            if config.get("text_channel_id"):
                return await interaction.response.send_message(
                    "⚠️ Server này đã được setup rồi!",
                    ephemeral=True
                )

            await interaction.response.defer(ephemeral=True)

            # ===============================
            # TẠO CATEGORY + CHANNEL
            # ===============================
            category = await guild.create_category("🏙️ THỊ TRẤN")

            text_channel = await guild.create_text_channel(
                "🌃 | Thị Trấn",
                category=category
            )

            voice_channel = await guild.create_voice_channel(
                "🗣️ | Nói Chuyện",
                category=category
            )

            print("[SETUP] Đã tạo channel thành công ✔")

            # ===============================
            # TẠO ROLE ALIVE-❤️‍🩹
            # Quyền giống như role "Thành Viên" mặc định của Discord
            # ===============================
            alive_role = await guild.create_role(
                name="Alive-❤️‍🩹",
                color=discord.Color.green(),
                permissions=discord.Permissions(
                    view_channel=True,
                    send_messages=True,
                    send_messages_in_threads=True,
                    read_message_history=True,
                    add_reactions=True,
                    use_external_emojis=True,
                    use_application_commands=True,
                    connect=True,
                    speak=True,
                    use_voice_activation=True,
                    change_nickname=True,
                ),
                reason="Anomalies — Alive role tự động tạo"
            )

            # ===============================
            # TẠO ROLE DEAD-☠️
            # ===============================
            dead_role = await guild.create_role(
                name="Dead-☠️",
                color=discord.Color.dark_grey(),
                reason="Anomalies — Dead role tự động tạo"
            )

            # ================================================================
            # LẤY TẤT CẢ SERVER ROLES (bỏ @everyone, bot roles, Alive, Dead)
            # ================================================================
            server_roles = [
                r for r in guild.roles
                if not r.is_default()
                and r != alive_role
                and r != dead_role
                and not r.managed
            ]

            # ================================================================
            # TEXT CHANNEL PERMISSIONS
            # ────────────────────────────────────────────────────────────────
            # • @everyone       : chỉ xem, không gửi tin
            # • Tất cả server roles : có thể gửi tin (send_messages=True)
            # • Alive / Dead    : "/" — không override, kế thừa từ role
            # ================================================================
            await text_channel.set_permissions(
                guild.default_role,
                read_messages=True,
                send_messages=False,
                add_reactions=False,
                reason="Anomalies — @everyone chỉ đọc"
            )

            text_roles_added = []
            for role in server_roles:
                try:
                    await text_channel.set_permissions(
                        role,
                        read_messages=True,
                        send_messages=True,
                        add_reactions=True,
                        reason=f"Anomalies — {role.name} có thể chat"
                    )
                    text_roles_added.append(role.name)
                except Exception as e:
                    print(f"[SETUP] Text perms lỗi cho {role.name}: {e}")

            print(f"[SETUP] Text channel: set cho {len(text_roles_added)} server roles ✔")

            # ================================================================
            # VOICE CHANNEL PERMISSIONS
            # ────────────────────────────────────────────────────────────────
            # • @everyone       : kết nối được, KHÔNG nói, KHÔNG chat
            # • Tất cả server roles : nói được (speak=True), không chat voice
            # • Alive / Dead    : "/" — không override, kế thừa từ role
            # ================================================================
            await voice_channel.set_permissions(
                guild.default_role,
                connect=True,
                speak=False,
                send_messages=False,
                stream=False,
                use_voice_activation=True,
                reason="Anomalies — @everyone vào nhưng không nói, không chat"
            )

            voice_roles_added = []
            for role in server_roles:
                try:
                    await voice_channel.set_permissions(
                        role,
                        connect=True,
                        speak=True,
                        send_messages=False,
                        use_voice_activation=True,
                        reason=f"Anomalies — {role.name} nói được trong voice"
                    )
                    voice_roles_added.append(role.name)
                except Exception as e:
                    print(f"[SETUP] Voice perms lỗi cho {role.name}: {e}")

            print(f"[SETUP] Voice channel: set cho {len(voice_roles_added)} server roles ✔")

            # ===============================
            # LƯU CONFIG LÊN MONGODB ATLAS
            # (upsert + merge default đã xử lý trong config_manager)
            # ===============================
            config["category_id"]      = str(category.id)
            config["text_channel_id"]  = str(text_channel.id)
            config["voice_channel_id"] = str(voice_channel.id)
            config["alive_role_id"]    = str(alive_role.id)
            config["dead_role_id"]     = str(dead_role.id)

            config.setdefault("max_players", 65)
            config.setdefault("min_players_to_start", 5)
            config.setdefault("countdown_minutes", 3)

            save_guild_config(guild_id, config, guild.name)

            print("[SETUP] Đã lưu config lên MongoDB ✔")

            # ===============================
            # GỌI INIT_GUILD TỪ bot.py
            # ===============================
            import sys
            bot_module = sys.modules.get("__main__")

            if hasattr(bot_module, "init_guild"):
                await bot_module.init_guild(guild_id, text_channel)
                print("[SETUP] init_guild chạy thành công ✔")
            else:
                print("[SETUP] Không tìm thấy init_guild trong bot.py")

            # ===============================
            # THÔNG BÁO HOÀN TẤT
            # ===============================
            roles_info = (
                f"\n🔧 Đã cấp quyền cho {len(server_roles)} server role "
                f"(text: chat | voice: nói)."
                if server_roles else ""
            )

            await interaction.followup.send(
                f"✅ **Setup hoàn tất!**\n\n"
                f"📂 Category: `{category.name}`\n"
                f"💬 Kênh chữ: `{text_channel.name}`\n"
                f"🔊 Kênh thoại: `{voice_channel.name}`\n\n"
                f"❤️‍🩹 **Alive Role** `{alive_role.name}` — quyền như Thành Viên (chat + nói)\n"
                f"💀 **Dead Role** `{dead_role.name}` — cấm chat & mic trong kênh game\n"
                f"☁️ Cấu hình đã được lưu trên MongoDB Atlas."
                f"{roles_info}",
                ephemeral=True
            )

        except Exception:
            print("[SETUP] ❌ LỖI:")
            traceback.print_exc()

            error_msg = traceback.format_exc()[-1500:]

            try:
                await interaction.followup.send(
                    f"❌ Setup thất bại:\n```{error_msg}```",
                    ephemeral=True
                )
            except Exception:
                try:
                    await interaction.response.send_message(
                        f"❌ Setup thất bại:\n```{error_msg}```",
                        ephemeral=True
                    )
                except Exception:
                    pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Setup(bot))
