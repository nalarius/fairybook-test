"""Helpers for querying and summarizing activity log data for the admin tool."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Sequence

from activity_log import ActivityLogEntry, ActivityLogPage, fetch_activity_entries
from admin_tool.constants import DEFAULT_PAGE_SIZE


@dataclass(slots=True)
class ActivityFilters:
    """Filter payload used by the activity explorer and dashboard."""

    types: tuple[str, ...] = tuple()
    actions: tuple[str, ...] = tuple()
    results: tuple[str, ...] = tuple()
    start_ts: datetime | None = None
    end_ts: datetime | None = None


@dataclass(slots=True)
class ActivitySummary:
    total_events: int
    failures: int
    distinct_users: int
    by_type: dict[str, int]
    by_action: dict[str, int]
    daily_counts: dict[str, int]
    failure_rate: float


def fetch_activity_page(
    filters: ActivityFilters,
    *,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> ActivityLogPage:
    """Fetch a page of activity logs using the shared filters."""

    return fetch_activity_entries(
        type_filter=filters.types,
        action_filter=filters.actions,
        result_filter=filters.results,
        start_ts=filters.start_ts,
        end_ts=filters.end_ts,
        cursor=cursor,
        limit=limit,
    )


def gather_activity_entries(
    filters: ActivityFilters,
    *,
    max_records: int = DEFAULT_PAGE_SIZE * 5,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> list[ActivityLogEntry]:
    """Load multiple pages of activity log entries up to ``max_records`` rows."""

    if max_records <= 0:
        return []

    entries: list[ActivityLogEntry] = []
    cursor: str | None = None

    while len(entries) < max_records:
        limit = min(page_size, max_records - len(entries))
        page = fetch_activity_page(filters, cursor=cursor, limit=limit)
        entries.extend(page.entries)
        if not page.has_more or not page.next_cursor:
            break
        cursor = page.next_cursor

    return entries


def summarize_entries(entries: Sequence[ActivityLogEntry]) -> ActivitySummary:
    """Compute aggregate metrics from a list of activity log entries."""

    total_events = len(entries)
    failures = sum(1 for entry in entries if entry.result == "fail")

    by_type_counter: Counter[str] = Counter(entry.type for entry in entries)
    by_action_counter: Counter[str] = Counter(entry.action for entry in entries)

    distinct_users = len({entry.user_id for entry in entries if entry.user_id})

    daily_counts: dict[str, int] = defaultdict(int)
    for entry in entries:
        day_key = entry.timestamp.date().isoformat()
        daily_counts[day_key] += 1

    failure_rate = (failures / total_events) if total_events else 0.0

    return ActivitySummary(
        total_events=total_events,
        failures=failures,
        distinct_users=distinct_users,
        by_type=dict(by_type_counter),
        by_action=dict(by_action_counter),
        daily_counts=dict(daily_counts),
        failure_rate=failure_rate,
    )


def default_filters_for_days(days: int) -> ActivityFilters:
    """Construct default filters covering the last ``days`` days (inclusive)."""

    if days <= 0:
        return ActivityFilters()

    end = datetime.now().astimezone()
    start = end - timedelta(days=days)
    return ActivityFilters(start_ts=start, end_ts=end)


def entry_to_row(entry: ActivityLogEntry) -> dict[str, Any]:
    """Serialize an ``ActivityLogEntry`` into a dictionary row for export."""

    return {
        "id": entry.id,
        "timestamp": entry.timestamp.isoformat(),
        "type": entry.type,
        "action": entry.action,
        "result": entry.result,
        "user_id": entry.user_id,
        "client_ip": entry.client_ip,
        "param1": entry.param1,
        "param2": entry.param2,
        "param3": entry.param3,
        "param4": entry.param4,
        "param5": entry.param5,
        "metadata": entry.metadata,
    }


__all__ = [
    "ActivityFilters",
    "ActivitySummary",
    "fetch_activity_page",
    "gather_activity_entries",
    "summarize_entries",
    "default_filters_for_days",
    "entry_to_row",
]
