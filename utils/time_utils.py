"""Time and timezone helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def format_kst(dt: datetime) -> str:
    aware = dt
    if dt.tzinfo is None:
        aware = dt.replace(tzinfo=timezone.utc)
    return aware.astimezone(KST).strftime("%Y-%m-%d %H:%M")


__all__ = ["KST", "format_kst"]
