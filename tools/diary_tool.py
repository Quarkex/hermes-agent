#!/usr/bin/env python3
"""
Episodic Diary Tool

Read, append, and consolidate Miaja's episodic diary at ~/diary/.
Structure: ~/diary/YYYY/MM/DD.md (day entries), summary.md (month/year).

This tool replaces manual mkdir + read_file + write_file sequences
for diary operations.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

DIARY_ROOT = Path(os.path.expanduser("~/diary"))


def _today() -> datetime:
    """Get current date in Atlantic/Canary timezone."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Atlantic/Canary"))
    except Exception:
        # Fallback: system local time (valiant is in Canary TZ)
        return datetime.now()


def _resolve_date(date_str: str = "") -> datetime:
    """Parse a date string or return today."""
    if not date_str or date_str.lower() in ("today", ""):
        return _today()
    if date_str.lower() == "yesterday":
        return _today() - timedelta(days=1)
    # Try various formats
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {date_str}. Use YYYY-MM-DD format.")


def _day_path(dt: datetime) -> Path:
    return DIARY_ROOT / f"{dt.year:04d}" / f"{dt.month:02d}" / f"{dt.day:02d}.md"


def _month_summary_path(dt: datetime) -> Path:
    return DIARY_ROOT / f"{dt.year:04d}" / f"{dt.month:02d}" / "summary.md"


def _year_summary_path(dt: datetime) -> Path:
    return DIARY_ROOT / f"{dt.year:04d}" / "summary.md"


# --- Operations ---

def _read(date_str: str = "", scope: str = "day") -> str:
    """Read a diary entry, month summary, or year summary."""
    dt = _resolve_date(date_str)

    if scope == "day":
        path = _day_path(dt)
    elif scope == "month":
        path = _month_summary_path(dt)
    elif scope == "year":
        path = _year_summary_path(dt)
    else:
        return json.dumps({"success": False, "error": f"Unknown scope: {scope}. Use: day, month, year"})

    if not path.exists():
        return json.dumps({
            "success": True,
            "path": str(path),
            "content": "",
            "exists": False,
            "message": f"No diary entry at {path}",
        })

    content = path.read_text(encoding="utf-8")
    return json.dumps({
        "success": True,
        "path": str(path),
        "content": content,
        "exists": True,
        "chars": len(content),
    }, ensure_ascii=False)


def _append(date_str: str, content: str) -> str:
    """Append content to a day's diary entry."""
    if not content or not content.strip():
        return json.dumps({"success": False, "error": "No content to append"})

    dt = _resolve_date(date_str)
    path = _day_path(dt)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = ""
    if path.exists():
        existing = path.read_text(encoding="utf-8")

    if existing:
        new_content = existing.rstrip() + "\n\n" + content.strip() + "\n"
    else:
        new_content = content.strip() + "\n"

    path.write_text(new_content, encoding="utf-8")

    return json.dumps({
        "success": True,
        "path": str(path),
        "action": "appended" if existing else "created",
        "total_chars": len(new_content),
    }, ensure_ascii=False)


def _list_entries(date_str: str = "", scope: str = "month") -> str:
    """List available diary entries for a month or year."""
    dt = _resolve_date(date_str) if date_str else _today()

    if scope == "month":
        month_dir = DIARY_ROOT / f"{dt.year:04d}" / f"{dt.month:02d}"
        if not month_dir.exists():
            return json.dumps({"success": True, "entries": [], "count": 0})
        entries = sorted([
            f.stem for f in month_dir.glob("*.md")
            if f.stem != "summary" and f.stem.isdigit()
        ])
        return json.dumps({
            "success": True,
            "year": dt.year,
            "month": dt.month,
            "entries": entries,
            "count": len(entries),
            "has_summary": (month_dir / "summary.md").exists(),
        })
    elif scope == "year":
        year_dir = DIARY_ROOT / f"{dt.year:04d}"
        if not year_dir.exists():
            return json.dumps({"success": True, "months": [], "count": 0})
        months = sorted([
            d.name for d in year_dir.iterdir()
            if d.is_dir() and d.name.isdigit()
        ])
        return json.dumps({
            "success": True,
            "year": dt.year,
            "months": months,
            "count": len(months),
            "has_summary": (year_dir / "summary.md").exists(),
        })
    else:
        return json.dumps({"success": False, "error": f"Unknown scope: {scope}. Use: month, year"})


def _write_summary(date_str: str, content: str, scope: str = "month") -> str:
    """Write or update a month or year summary."""
    if not content or not content.strip():
        return json.dumps({"success": False, "error": "No content for summary"})

    dt = _resolve_date(date_str)

    if scope == "month":
        path = _month_summary_path(dt)
    elif scope == "year":
        path = _year_summary_path(dt)
    else:
        return json.dumps({"success": False, "error": f"Unknown scope: {scope}. Use: month, year"})

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")

    return json.dumps({
        "success": True,
        "path": str(path),
        "chars": len(content),
    }, ensure_ascii=False)


# --- Main entry point ---

def diary(
    action: str = "read",
    date: str = "",
    content: str = "",
    scope: str = "day",
) -> str:
    """Main entry point for the diary tool."""
    try:
        if action == "read":
            return _read(date_str=date, scope=scope)
        elif action == "append":
            return _append(date_str=date, content=content)
        elif action == "list":
            return _list_entries(date_str=date, scope=scope)
        elif action == "write_summary":
            return _write_summary(date_str=date, content=content, scope=scope)
        else:
            return json.dumps({
                "success": False,
                "error": f"Unknown action: {action}. Use: read, append, list, write_summary",
            })
    except Exception as e:
        logger.exception("diary tool failed")
        return json.dumps({"success": False, "error": f"{type(e).__name__}: {str(e)}"})


# --- Schema ---

DIARY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "diary",
        "description": (
            "Miaja's episodic diary at ~/diary/. Read, append, and manage narrative "
            "diary entries organized by date (YYYY/MM/DD.md). Actions: 'read' (read an entry), "
            "'append' (add content to a day), 'list' (list available entries), "
            "'write_summary' (write month/year summary)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "append", "list", "write_summary"],
                    "description": "Operation: 'read' a day/month/year entry, 'append' to a day, "
                                   "'list' available entries, 'write_summary' for month/year.",
                },
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format, or 'today'/'yesterday'. "
                                   "For month scope, only year+month matter (e.g. '2026-05-01'). "
                                   "Defaults to today.",
                },
                "content": {
                    "type": "string",
                    "description": "Text content to append or write. Required for 'append' and 'write_summary'.",
                },
                "scope": {
                    "type": "string",
                    "enum": ["day", "month", "year"],
                    "description": "Scope for read/list/write_summary. 'day' for daily entries, "
                                   "'month' for monthly, 'year' for yearly. Default: 'day' for read, 'month' for list.",
                    "default": "day",
                },
            },
            "required": ["action"],
        },
    },
}


# --- Registry ---
from tools.registry import registry

registry.register(
    name="diary",
    toolset="diary",
    schema=DIARY_SCHEMA,
    handler=lambda args, **kw: diary(
        action=args.get("action", "read"),
        date=args.get("date", ""),
        content=args.get("content", ""),
        scope=args.get("scope", "day"),
    ),
    emoji="📓",
)
