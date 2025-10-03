from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from activity_log import ActivityLogEntry, ActivityLogPage
from admin_tool.activity_service import (
    ActivityFilters,
    default_filters_for_days,
    gather_activity_entries,
    entry_to_row,
    summarize_entries,
)


def _build_entry(
    *,
    id: str,
    type: str,
    action: str,
    result: str,
    timestamp: datetime,
    user_id: str | None = None,
    metadata: dict | None = None,
) -> ActivityLogEntry:
    return ActivityLogEntry(
        id=id,
        type=type,
        action=action,
        result=result,
        user_id=user_id,
        client_ip=None,
        timestamp=timestamp,
        year=timestamp.year,
        month=timestamp.month,
        day=timestamp.day,
        param1=None,
        param2=None,
        param3=None,
        param4=None,
        param5=None,
        metadata=metadata,
    )


def test_summarize_entries():
    ts = datetime(2024, 5, 1, 10, 0, tzinfo=timezone.utc)
    entries = [
        _build_entry(id="1", type="story", action="story start", result="success", timestamp=ts, user_id="u1"),
        _build_entry(id="2", type="story", action="story save", result="fail", timestamp=ts, user_id="u1"),
        _build_entry(id="3", type="moderation", action="content hide", result="success", timestamp=ts, user_id="admin"),
    ]

    summary = summarize_entries(entries)
    assert summary.total_events == 3
    assert summary.failures == 1
    assert summary.distinct_users == 2
    assert summary.by_type["story"] == 2
    assert summary.by_action["content hide"] == 1
    assert pytest.approx(summary.failure_rate, rel=1e-6) == 1 / 3


def test_gather_activity_entries_combines_pages(monkeypatch):
    filters = ActivityFilters()
    ts = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)
    entries_page1 = [_build_entry(id="1", type="story", action="story start", result="success", timestamp=ts)]
    entries_page2 = [_build_entry(id="2", type="story", action="story save", result="success", timestamp=ts)]

    pages = [
        ActivityLogPage(entries=entries_page1, next_cursor="cursor-1", has_more=True),
        ActivityLogPage(entries=entries_page2, next_cursor=None, has_more=False),
    ]

    def fake_fetch(filters_param, *, cursor=None, limit):  # noqa: ARG001
        assert limit > 0
        if not pages:
            return ActivityLogPage(entries=[], next_cursor=None, has_more=False)
        return pages.pop(0)

    monkeypatch.setattr("admin_tool.activity_service.fetch_activity_page", fake_fetch)

    collected = gather_activity_entries(filters, max_records=10, page_size=5)
    assert [entry.id for entry in collected] == ["1", "2"]


def test_default_filters_for_days():
    filters = default_filters_for_days(7)
    assert isinstance(filters, ActivityFilters)
    assert filters.start_ts is not None and filters.end_ts is not None

    zero_filters = default_filters_for_days(0)
    assert zero_filters.start_ts is None
    assert zero_filters.end_ts is None


def test_entry_to_row_serializes():
    ts = datetime(2024, 5, 1, 10, 0, tzinfo=timezone.utc)
    entry = _build_entry(id="1", type="story", action="story start", result="success", timestamp=ts, user_id="u1")
    entry.metadata = {"key": "value"}
    row = entry_to_row(entry)
    assert row["id"] == "1"
    assert row["timestamp"].startswith("2024-05-01")
    assert row["metadata"] == {"key": "value"}
