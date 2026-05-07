#!/usr/bin/env python3
"""
Telethon Telegram Userbot Tool

Read Telegram chats, search messages, and list dialogs as a user account
(not bot). Required for accessing private groups, reading chat history,
and searching messages across chats.

Requires:
  - telethon package installed
  - Authenticated session at ~/.hermes/telethon_session.session
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# --- Config ---
SESSION_PATH = os.path.expanduser("~/.hermes/telethon_session")
API_ID = 30292187
API_HASH = "399628dc40eef2f2db5b0fbd860d9421"

# Cache the client across calls within the same process
_client = None
_loop = None


def _get_loop():
    """Get or create an event loop that persists across calls."""
    global _loop
    if _loop is None or _loop.is_closed():
        try:
            _loop = asyncio.get_event_loop()
            if _loop.is_closed():
                raise RuntimeError
        except RuntimeError:
            _loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_loop)
    return _loop


async def _get_client():
    """Get or create a connected Telethon client."""
    global _client
    if _client is not None and _client.is_connected():
        return _client

    try:
        from telethon import TelegramClient
    except ImportError:
        raise RuntimeError(
            "telethon not installed. Run: "
            "/home/quarkex/.hermes/hermes-agent/venv/bin/pip3 install telethon"
        )

    if not os.path.exists(SESSION_PATH + ".session"):
        raise RuntimeError(
            f"No Telethon session at {SESSION_PATH}.session. "
            "Run telethon_login.py first."
        )

    _client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await _client.connect()
    if not await _client.is_user_authorized():
        raise RuntimeError("Telethon session expired. Re-authenticate.")
    return _client


def _format_date(dt) -> str:
    """Format a datetime to ISO-ish string."""
    if dt is None:
        return ""
    if hasattr(dt, "strftime"):
        return dt.strftime("%Y-%m-%d %H:%M")
    return str(dt)


async def _resolve_sender_name(msg, entity_cache: dict) -> str:
    """Resolve sender name from message, with caching."""
    sid = msg.sender_id
    if sid is None:
        return "unknown"
    if sid in entity_cache:
        return entity_cache[sid]

    try:
        sender = await msg.get_sender()
        if sender is None:
            name = str(sid)
        elif hasattr(sender, "first_name"):
            first = sender.first_name or ""
            last = sender.last_name or ""
            name = f"{first} {last}".strip() or str(sid)
        elif hasattr(sender, "title"):
            name = sender.title or str(sid)
        else:
            name = str(sid)
    except Exception:
        name = str(sid)

    entity_cache[sid] = name
    return name


# --- Operations ---

async def _list_dialogs(limit: int = 30) -> str:
    client = await _get_client()
    dialogs = []
    async for d in client.iter_dialogs(limit=limit):
        dtype = "user"
        if d.is_group:
            dtype = "group"
        elif d.is_channel:
            dtype = "channel"
        dialogs.append({
            "id": d.id,
            "name": d.name or "(unnamed)",
            "type": dtype,
            "unread": d.unread_count,
            "last_message_date": _format_date(d.date),
        })
    return json.dumps({"success": True, "dialogs": dialogs, "count": len(dialogs)},
                       ensure_ascii=False)


async def _read_messages(
    chat_id,
    limit: int = 50,
    search: Optional[str] = None,
    offset_id: int = 0,
    reverse: bool = False,
    min_date: Optional[str] = None,
    max_date: Optional[str] = None,
) -> str:
    client = await _get_client()

    # Parse chat_id (could be int or string)
    try:
        chat_id = int(chat_id)
    except (ValueError, TypeError):
        pass  # keep as string for username resolution

    entity = await client.get_entity(chat_id)

    kwargs: Dict[str, Any] = {"limit": min(limit, 500)}
    if search:
        kwargs["search"] = search
    if offset_id:
        kwargs["offset_id"] = offset_id
    if reverse:
        kwargs["reverse"] = True

    # Date filters
    if min_date:
        try:
            kwargs["offset_date"] = datetime.fromisoformat(min_date).replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            pass
    # Note: Telethon doesn't have a native max_date filter for iter_messages,
    # but we can filter manually

    max_dt = None
    if max_date:
        try:
            max_dt = datetime.fromisoformat(max_date).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    messages = []
    entity_cache = {}
    async for msg in client.iter_messages(entity, **kwargs):
        if max_dt and msg.date and msg.date > max_dt:
            continue

        sender_name = await _resolve_sender_name(msg, entity_cache)

        m = {
            "id": msg.id,
            "date": _format_date(msg.date),
            "sender": sender_name,
            "sender_id": msg.sender_id,
            "text": msg.text or "",
        }
        if msg.media and not msg.text:
            m["has_media"] = True
            m["media_type"] = type(msg.media).__name__
        if msg.reply_to:
            m["reply_to_id"] = msg.reply_to.reply_to_msg_id

        messages.append(m)

    # Get total count efficiently
    total = None
    try:
        result = await client.get_messages(entity, limit=1)
        total = result.total
    except Exception:
        pass

    return json.dumps({
        "success": True,
        "chat": getattr(entity, "title", None) or getattr(entity, "first_name", str(chat_id)),
        "chat_id": getattr(entity, "id", chat_id),
        "messages": messages,
        "returned": len(messages),
        "total_in_chat": total,
    }, ensure_ascii=False)


async def _get_message_count(chat_id) -> str:
    client = await _get_client()
    try:
        chat_id = int(chat_id)
    except (ValueError, TypeError):
        pass
    entity = await client.get_entity(chat_id)
    result = await client.get_messages(entity, limit=1)
    name = getattr(entity, "title", None) or getattr(entity, "first_name", str(chat_id))
    return json.dumps({
        "success": True,
        "chat": name,
        "chat_id": getattr(entity, "id", chat_id),
        "total": result.total,
    }, ensure_ascii=False)


# --- Sync wrappers ---

def telethon_read(
    action: str = "list_dialogs",
    chat_id: str = "",
    limit: int = 50,
    search: str = "",
    offset_id: int = 0,
    reverse: bool = False,
    min_date: str = "",
    max_date: str = "",
) -> str:
    """Main entry point for the telethon tool."""
    loop = _get_loop()
    try:
        if action == "list_dialogs":
            return loop.run_until_complete(_list_dialogs(limit=limit))
        elif action == "read_messages":
            if not chat_id:
                return json.dumps({"success": False, "error": "chat_id is required for read_messages"})
            return loop.run_until_complete(_read_messages(
                chat_id=chat_id,
                limit=limit,
                search=search or None,
                offset_id=offset_id,
                reverse=reverse,
                min_date=min_date or None,
                max_date=max_date or None,
            ))
        elif action == "message_count":
            if not chat_id:
                return json.dumps({"success": False, "error": "chat_id is required for message_count"})
            return loop.run_until_complete(_get_message_count(chat_id=chat_id))
        else:
            return json.dumps({"success": False, "error": f"Unknown action: {action}. Use: list_dialogs, read_messages, message_count"})
    except Exception as e:
        logger.exception("telethon_read failed")
        return json.dumps({"success": False, "error": f"{type(e).__name__}: {str(e)}"})


# --- Check function ---

def check_telethon_requirements():
    """Check if telethon is available and session exists."""
    try:
        import telethon  # noqa: F401
    except ImportError:
        return "telethon package not installed"
    if not os.path.exists(SESSION_PATH + ".session"):
        return "No telethon session file found"
    return None


# --- Schema ---

TELETHON_READ_SCHEMA = {
    "type": "function",
    "function": {
        "name": "telethon_read",
        "description": (
            "Read Telegram chats as a user account (not bot). Access private groups, "
            "search messages, read chat history. Actions: 'list_dialogs' (list chats), "
            "'read_messages' (read/search messages in a chat), 'message_count' (count messages)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list_dialogs", "read_messages", "message_count"],
                    "description": "Operation to perform. 'list_dialogs' shows available chats, "
                                   "'read_messages' reads messages from a specific chat, "
                                   "'message_count' returns the total message count for a chat.",
                },
                "chat_id": {
                    "type": "string",
                    "description": "Chat/group/channel ID (numeric) or username. Required for read_messages and message_count. "
                                   "Groups are negative (e.g. '-1001234567890').",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max messages to return (default: 50, max: 500). For list_dialogs, max dialogs to list.",
                    "default": 50,
                },
                "search": {
                    "type": "string",
                    "description": "Search query to filter messages (case-insensitive). Only for read_messages.",
                },
                "offset_id": {
                    "type": "integer",
                    "description": "Start reading from this message ID (for pagination). Messages with ID < offset_id are returned.",
                    "default": 0,
                },
                "reverse": {
                    "type": "boolean",
                    "description": "If true, return messages in chronological order (oldest first). Default: newest first.",
                    "default": False,
                },
                "min_date": {
                    "type": "string",
                    "description": "Only messages after this ISO date (e.g. '2026-05-01'). For read_messages.",
                },
                "max_date": {
                    "type": "string",
                    "description": "Only messages before this ISO date (e.g. '2026-05-07'). For read_messages.",
                },
            },
            "required": ["action"],
        },
    },
}


# --- Registry ---
from tools.registry import registry

registry.register(
    name="telethon_read",
    toolset="telethon",
    schema=TELETHON_READ_SCHEMA,
    handler=lambda args, **kw: telethon_read(
        action=args.get("action", "list_dialogs"),
        chat_id=args.get("chat_id", ""),
        limit=args.get("limit", 50),
        search=args.get("search", ""),
        offset_id=args.get("offset_id", 0),
        reverse=args.get("reverse", False),
        min_date=args.get("min_date", ""),
        max_date=args.get("max_date", ""),
    ),
    check_fn=check_telethon_requirements,
    emoji="📱",
)
