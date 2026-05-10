from __future__ import annotations

import asyncio
import collections
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator, Deque

import disnake
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TOKEN: str = os.environ["DISCORD_TOKEN"]
MAX_LOG_ENTRIES: int = 200
MAX_METRIC_POINTS: int = 120  # ~2 hours at 1 sample/min

# ---------------------------------------------------------------------------
# In-memory stores (shared across all endpoints via the same event loop)
# ---------------------------------------------------------------------------

# Rolling event log — populated by bot events
event_log: Deque[dict] = collections.deque(maxlen=MAX_LOG_ENTRIES)

# Latency history — populated by the metrics background task
latency_history: Deque[dict] = collections.deque(maxlen=MAX_METRIC_POINTS)

# Connected WebSocket clients for live-push
_ws_clients: set[WebSocket] = set()


def _log(kind: str, **payload) -> None:
    event_log.appendleft(
        {"ts": datetime.now(timezone.utc).isoformat(), "kind": kind, **payload}
    )


# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------

intents = disnake.Intents.default()
intents.members = True
intents.message_content = True

bot = disnake.AutoShardedInteractionBot(intents=intents)


@bot.event
async def on_ready() -> None:
    _log("ready", bot_id=str(bot.user.id), bot_name=str(bot.user))
    print(f"[bot] Logged in as {bot.user} (id={bot.user.id})")


@bot.event
async def on_guild_join(guild: disnake.Guild) -> None:
    _log("guild_join", guild_id=str(guild.id), guild_name=guild.name)


@bot.event
async def on_guild_remove(guild: disnake.Guild) -> None:
    _log("guild_leave", guild_id=str(guild.id), guild_name=guild.name)


@bot.event
async def on_member_join(member: disnake.Member) -> None:
    _log(
        "member_join",
        guild_id=str(member.guild.id),
        user_id=str(member.id),
        username=str(member),
    )


@bot.event
async def on_member_remove(member: disnake.Member) -> None:
    _log(
        "member_leave",
        guild_id=str(member.guild.id),
        user_id=str(member.id),
        username=str(member),
    )


@bot.event
async def on_message(message: disnake.Message) -> None:
    if message.author.bot:
        return
    _log(
        "message",
        guild_id=str(message.guild.id) if message.guild else None,
        channel_id=str(message.channel.id),
        user_id=str(message.author.id),
        preview=message.content[:80],
    )


# ---------------------------------------------------------------------------
# Background task — collect latency metrics every 60 s
# ---------------------------------------------------------------------------

async def _metrics_collector() -> None:
    await bot.wait_until_ready()
    while not bot.is_closed():
        latency_history.append(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "latency_ms": round(bot.latency * 1000, 2),
                "guild_count": len(bot.guilds),
                "shard_count": bot.shard_count or 1,
            }
        )
        # Push live update to all connected WS clients
        if _ws_clients:
            snapshot = latency_history[0]
            dead: set[WebSocket] = set()
            for ws in _ws_clients:
                try:
                    await ws.send_json({"event": "metrics", "data": snapshot})
                except Exception:
                    dead.add(ws)
            _ws_clients.difference_update(dead)
        await asyncio.sleep(60)


# ---------------------------------------------------------------------------
# Lifespan — single event loop shared by bot + FastAPI
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    bot_task = asyncio.create_task(bot.start(TOKEN), name="discord-bot")
    metrics_task = asyncio.create_task(_metrics_collector(), name="metrics-collector")

    try:
        yield
    finally:
        for task in (metrics_task, bot_task):
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        if not bot.is_closed():
            await bot.close()


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(title="Anomalies Dashboard", version="2.0.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_bot_ready() -> None:
    if bot.user is None:
        raise HTTPException(
            status_code=503,
            detail="Bot is still starting up — please retry in a moment.",
        )


def _get_guild(guild_id: int) -> disnake.Guild:
    _require_bot_ready()
    guild = bot.get_guild(guild_id)
    if guild is None:
        raise HTTPException(status_code=404, detail="Guild not found or bot is not a member.")
    return guild


# ---------------------------------------------------------------------------
# Pydantic request bodies
# ---------------------------------------------------------------------------

class SendMessageBody(BaseModel):
    guild_id: int
    channel_id: int
    content: str
    tts: bool = False


class UpdateStatusBody(BaseModel):
    # "online" | "idle" | "dnd" | "invisible"
    status: str = "online"
    # "playing" | "listening" | "watching" | "streaming" | "competing"
    activity_type: str = "playing"
    activity_name: str = ""


# ---------------------------------------------------------------------------
# ① /api/dash/info — overview (original, preserved)
# ---------------------------------------------------------------------------

@app.get("/api/dash/info")
async def dash_info() -> JSONResponse:
    _require_bot_ready()
    guilds = [
        {
            "id": str(g.id),
            "name": g.name,
            "member_count": g.member_count,
            "icon": str(g.icon.url) if g.icon else None,
        }
        for g in bot.guilds
    ]
    return JSONResponse(
        {
            "bot": {
                "id": str(bot.user.id),
                "name": bot.user.name,
                "discriminator": bot.user.discriminator,
                "avatar": str(bot.user.avatar.url) if bot.user.avatar else None,
                "shard_count": bot.shard_count,
            },
            "stats": {
                "guild_count": len(bot.guilds),
                "user_count": sum(g.member_count or 0 for g in bot.guilds),
                "latency_ms": round(bot.latency * 1000, 2),
            },
            "guilds": guilds,
        }
    )


# ---------------------------------------------------------------------------
# ② /api/dash/guild/{guild_id} — guild detail (original, preserved)
# ---------------------------------------------------------------------------

@app.get("/api/dash/guild/{guild_id}")
async def guild_info(guild_id: int) -> JSONResponse:
    guild = _get_guild(guild_id)
    return JSONResponse(
        {
            "id": str(guild.id),
            "name": guild.name,
            "member_count": guild.member_count,
            "icon": str(guild.icon.url) if guild.icon else None,
            "owner_id": str(guild.owner_id),
            "channels": [
                {"id": str(c.id), "name": c.name, "type": str(c.type)}
                for c in guild.channels
            ],
            "roles": [
                {"id": str(r.id), "name": r.name, "color": str(r.color)}
                for r in guild.roles
            ],
        }
    )


# ---------------------------------------------------------------------------
# ③ NEW — /api/dash/members/{guild_id}?q=name&limit=50
#    Search / list members of a guild
# ---------------------------------------------------------------------------

@app.get("/api/dash/members/{guild_id}")
async def guild_members(
    guild_id: int, q: str = "", limit: int = 50
) -> JSONResponse:
    guild = _get_guild(guild_id)
    limit = min(max(1, limit), 500)

    members = [
        m for m in guild.members
        if q.lower() in m.display_name.lower() or q.lower() in str(m).lower()
    ][:limit]

    return JSONResponse(
        {
            "guild_id": str(guild_id),
            "total_matched": len(members),
            "members": [
                {
                    "id": str(m.id),
                    "username": str(m),
                    "display_name": m.display_name,
                    "bot": m.bot,
                    "avatar": str(m.avatar.url) if m.avatar else None,
                    "joined_at": m.joined_at.isoformat() if m.joined_at else None,
                    "roles": [str(r.id) for r in m.roles if r.name != "@everyone"],
                    "top_role": m.top_role.name,
                }
                for m in members
            ],
        }
    )


# ---------------------------------------------------------------------------
# ④ NEW — /api/dash/channels/{guild_id}
#    Detailed channel list with topic, slowmode, NSFW, permissions
# ---------------------------------------------------------------------------

@app.get("/api/dash/channels/{guild_id}")
async def guild_channels(guild_id: int) -> JSONResponse:
    guild = _get_guild(guild_id)

    channels_out = []
    for ch in sorted(guild.channels, key=lambda c: c.position):
        entry: dict = {
            "id": str(ch.id),
            "name": ch.name,
            "type": str(ch.type),
            "position": ch.position,
        }
        if isinstance(ch, disnake.TextChannel):
            entry.update(
                {
                    "topic": ch.topic,
                    "slowmode_delay": ch.slowmode_delay,
                    "nsfw": ch.nsfw,
                    "last_message_id": str(ch.last_message_id) if ch.last_message_id else None,
                }
            )
        elif isinstance(ch, disnake.VoiceChannel):
            entry.update({"bitrate": ch.bitrate, "user_limit": ch.user_limit})
        elif isinstance(ch, disnake.CategoryChannel):
            entry["child_count"] = len(ch.channels)
        channels_out.append(entry)

    return JSONResponse({"guild_id": str(guild_id), "channels": channels_out})


# ---------------------------------------------------------------------------
# ⑤ NEW — /api/dash/roles/{guild_id}
#    Full role list with permission value breakdown
# ---------------------------------------------------------------------------

@app.get("/api/dash/roles/{guild_id}")
async def guild_roles(guild_id: int) -> JSONResponse:
    guild = _get_guild(guild_id)

    roles_out = []
    for role in sorted(guild.roles, key=lambda r: r.position, reverse=True):
        perms = {p: v for p, v in role.permissions}
        roles_out.append(
            {
                "id": str(role.id),
                "name": role.name,
                "color": str(role.color),
                "hoist": role.hoist,
                "mentionable": role.mentionable,
                "position": role.position,
                "managed": role.managed,
                "member_count": sum(1 for m in guild.members if role in m.roles),
                "permissions": perms,
            }
        )

    return JSONResponse({"guild_id": str(guild_id), "roles": roles_out})


# ---------------------------------------------------------------------------
# ⑥ NEW — POST /api/dash/message
#    Send a message to any channel the bot can see
# ---------------------------------------------------------------------------

@app.post("/api/dash/message")
async def send_message(body: SendMessageBody) -> JSONResponse:
    _require_bot_ready()

    channel = bot.get_channel(body.channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found.")
    if not isinstance(channel, (disnake.TextChannel, disnake.Thread)):
        raise HTTPException(status_code=400, detail="Target channel is not a text channel.")
    if not channel.permissions_for(channel.guild.me).send_messages:
        raise HTTPException(status_code=403, detail="Bot lacks Send Messages permission.")
    if len(body.content) > 2000:
        raise HTTPException(status_code=400, detail="Content exceeds 2000 characters.")

    msg = await channel.send(body.content, tts=body.tts)
    _log(
        "api_message_sent",
        channel_id=str(body.channel_id),
        guild_id=str(body.guild_id),
        message_id=str(msg.id),
    )
    return JSONResponse(
        {"ok": True, "message_id": str(msg.id), "channel_id": str(body.channel_id)}
    )


# ---------------------------------------------------------------------------
# ⑦ NEW — PUT /api/dash/status
#    Change bot presence / activity at runtime without restarting
# ---------------------------------------------------------------------------

_ACTIVITY_MAP = {
    "playing": disnake.ActivityType.playing,
    "listening": disnake.ActivityType.listening,
    "watching": disnake.ActivityType.watching,
    "competing": disnake.ActivityType.competing,
}

_STATUS_MAP = {
    "online": disnake.Status.online,
    "idle": disnake.Status.idle,
    "dnd": disnake.Status.dnd,
    "invisible": disnake.Status.invisible,
}


@app.put("/api/dash/status")
async def update_status(body: UpdateStatusBody) -> JSONResponse:
    _require_bot_ready()

    status = _STATUS_MAP.get(body.status)
    if status is None:
        raise HTTPException(status_code=400, detail=f"Invalid status '{body.status}'. Use: online, idle, dnd, invisible.")

    activity_type = _ACTIVITY_MAP.get(body.activity_type)
    if activity_type is None:
        raise HTTPException(status_code=400, detail=f"Invalid activity_type '{body.activity_type}'.")

    activity = disnake.Activity(type=activity_type, name=body.activity_name) if body.activity_name else None
    await bot.change_presence(status=status, activity=activity)

    _log("status_changed", status=body.status, activity_type=body.activity_type, activity_name=body.activity_name)
    return JSONResponse({"ok": True, "status": body.status, "activity": body.activity_name})


# ---------------------------------------------------------------------------
# ⑧ NEW — GET /api/dash/logs?kind=&limit=50
#    In-memory rolling event log (bot events + API actions)
# ---------------------------------------------------------------------------

@app.get("/api/dash/logs")
async def get_logs(kind: str = "", limit: int = 50) -> JSONResponse:
    limit = min(max(1, limit), MAX_LOG_ENTRIES)
    entries = [e for e in event_log if not kind or e.get("kind") == kind][:limit]
    return JSONResponse({"total": len(entries), "entries": entries})


# ---------------------------------------------------------------------------
# ⑨ NEW — GET /api/dash/metrics
#    Historical latency + guild count snapshots (sampled every 60 s)
# ---------------------------------------------------------------------------

@app.get("/api/dash/metrics")
async def get_metrics() -> JSONResponse:
    _require_bot_ready()
    return JSONResponse(
        {
            "current": {
                "latency_ms": round(bot.latency * 1000, 2),
                "guild_count": len(bot.guilds),
                "uptime_since": event_log[-1]["ts"] if event_log else None,
            },
            "history": list(latency_history),
        }
    )


# ---------------------------------------------------------------------------
# ⑩ NEW — WebSocket /ws/stats
#    Persistent connection receives a live metrics push every 60 s
# ---------------------------------------------------------------------------

@app.websocket("/ws/stats")
async def ws_stats(websocket: WebSocket) -> None:
    await websocket.accept()
    _ws_clients.add(websocket)

    # Send current snapshot immediately on connect
    if bot.user is not None:
        await websocket.send_json(
            {
                "event": "connected",
                "data": {
                    "bot_name": str(bot.user),
                    "latency_ms": round(bot.latency * 1000, 2),
                    "guild_count": len(bot.guilds),
                },
            }
        )

    try:
        while True:
            # Keep connection alive; wait for client ping or disconnect
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(websocket)


# ---------------------------------------------------------------------------
# ⑪ NEW — GET /api/dash/audit/{guild_id}
#    Kéo audit log Discord: ai kick, đổi role, xóa tin nhắn...
#    Params: limit (1-100), action (tên hành động, ví dụ "member_kick")
# ---------------------------------------------------------------------------

_AUDIT_ACTION_MAP: dict[str, disnake.AuditLogAction] = {
    "guild_update":        disnake.AuditLogAction.guild_update,
    "channel_create":      disnake.AuditLogAction.channel_create,
    "channel_update":      disnake.AuditLogAction.channel_update,
    "channel_delete":      disnake.AuditLogAction.channel_delete,
    "kick":                disnake.AuditLogAction.kick,
    "member_prune":        disnake.AuditLogAction.member_prune,
    "ban":                 disnake.AuditLogAction.ban,
    "unban":               disnake.AuditLogAction.unban,
    "member_update":       disnake.AuditLogAction.member_update,
    "member_role_update":  disnake.AuditLogAction.member_role_update,
    "member_move":         disnake.AuditLogAction.member_move,
    "member_disconnect":   disnake.AuditLogAction.member_disconnect,
    "role_create":         disnake.AuditLogAction.role_create,
    "role_update":         disnake.AuditLogAction.role_update,
    "role_delete":         disnake.AuditLogAction.role_delete,
    "invite_create":       disnake.AuditLogAction.invite_create,
    "invite_delete":       disnake.AuditLogAction.invite_delete,
    "message_delete":      disnake.AuditLogAction.message_delete,
    "message_bulk_delete": disnake.AuditLogAction.message_bulk_delete,
    "message_pin":         disnake.AuditLogAction.message_pin,
    "message_unpin":       disnake.AuditLogAction.message_unpin,
    "bot_add":             disnake.AuditLogAction.bot_add,
    "thread_create":       disnake.AuditLogAction.thread_create,
    "thread_update":       disnake.AuditLogAction.thread_update,
    "thread_delete":       disnake.AuditLogAction.thread_delete,
}


@app.get("/api/dash/audit/{guild_id}")
async def guild_audit(
    guild_id: int,
    limit: int = 50,
    action: str = "",
) -> JSONResponse:
    guild = _get_guild(guild_id)

    # Check bot has permission to view audit log
    if not guild.me.guild_permissions.view_audit_log:
        raise HTTPException(status_code=403, detail="Bot lacks View Audit Log permission.")

    limit = min(max(1, limit), 100)
    action_filter: disnake.AuditLogAction | None = None

    if action:
        action_filter = _AUDIT_ACTION_MAP.get(action)
        if action_filter is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown action '{action}'. Valid values: {', '.join(_AUDIT_ACTION_MAP)}",
            )

    entries = []
    async for entry in guild.audit_logs(limit=limit, action=action_filter):
        target_info: dict | None = None
        if isinstance(entry.target, disnake.Member):
            target_info = {"type": "member", "id": str(entry.target.id), "name": str(entry.target)}
        elif isinstance(entry.target, disnake.User):
            target_info = {"type": "user", "id": str(entry.target.id), "name": str(entry.target)}
        elif isinstance(entry.target, (disnake.TextChannel, disnake.VoiceChannel, disnake.CategoryChannel)):
            target_info = {"type": "channel", "id": str(entry.target.id), "name": entry.target.name}
        elif isinstance(entry.target, disnake.Role):
            target_info = {"type": "role", "id": str(entry.target.id), "name": entry.target.name}
        elif entry.target is not None:
            target_info = {"type": "unknown", "id": str(getattr(entry.target, "id", "?"))}

        changes: list[dict] = []
        for change in entry.changes.before.__dict__:
            before_val = getattr(entry.changes.before, change, None)
            after_val = getattr(entry.changes.after, change, None)
            changes.append({"field": change, "before": str(before_val), "after": str(after_val)})

        entries.append(
            {
                "id": str(entry.id),
                "action": str(entry.action).replace("AuditLogAction.", ""),
                "user": {
                    "id": str(entry.user.id) if entry.user else None,
                    "name": str(entry.user) if entry.user else None,
                },
                "target": target_info,
                "reason": entry.reason,
                "created_at": entry.created_at.isoformat(),
                "changes": changes,
            }
        )

    return JSONResponse(
        {
            "guild_id": str(guild_id),
            "action_filter": action or None,
            "count": len(entries),
            "entries": entries,
            "valid_actions": list(_AUDIT_ACTION_MAP.keys()),
        }
    )


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "bot_ready": bot.user is not None,
            "latency_ms": round(bot.latency * 1000, 2) if bot.user else None,
            "guild_count": len(bot.guilds) if bot.user else 0,
            "ws_clients": len(_ws_clients),
            "log_entries": len(event_log),
        }
    )
