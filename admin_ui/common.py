"""Shared helpers for admin UI views."""
from __future__ import annotations

from datetime import date, datetime, time as datetime_time, timedelta, timezone
from typing import Any

import streamlit as st

try:  # Optional analytics helpers
    import altair as alt  # type: ignore
except Exception:  # pragma: no cover
    alt = None

try:  # Optional DataFrame support
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover
    pd = None

from admin_tool.activity_service import ActivityFilters


def apply_date_filters(state: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    start_date: date = state.get("start_date") or (date.today() - timedelta(days=7))
    end_date: date = state.get("end_date") or date.today()

    if start_date > end_date:
        start_date, end_date = end_date, start_date
        state["start_date"] = start_date
        state["end_date"] = end_date

    start_dt = datetime.combine(start_date, datetime_time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end_date, datetime_time.max, tzinfo=timezone.utc)
    return start_dt, end_dt


def parse_action_tokens(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return tuple()
    tokens = {token.strip() for token in raw.split(",") if token.strip()}
    return tuple(sorted(tokens))


def filters_from_state(state: dict[str, Any]) -> ActivityFilters:
    start_ts, end_ts = apply_date_filters(state)
    types = tuple(state.get("types") or ())
    actions = tuple(state.get("actions") or ())
    results = tuple(state.get("results") or ())
    return ActivityFilters(
        types=types,
        actions=actions,
        results=results,
        start_ts=start_ts,
        end_ts=end_ts,
    )


def render_summary_cards(summary) -> None:
    cols = st.columns(3)
    cols[0].metric("총 이벤트", f"{summary.total_events:,}")
    cols[1].metric("실패", f"{summary.failures:,}", delta=f"{summary.failure_rate*100:.1f}%")
    cols[2].metric("고유 사용자", f"{summary.distinct_users:,}")


def render_activity_chart(summary, granularity: str) -> None:
    if not pd or not alt:  # pragma: no cover - optional charting dependencies
        return

    counts_map = summary.hourly_counts if granularity == "hourly" else summary.daily_counts
    if not counts_map:
        return

    df = pd.DataFrame({"bucket": list(counts_map.keys()), "count": list(counts_map.values())})

    if granularity == "hourly":
        df["bucket_dt"] = pd.to_datetime(df["bucket"], utc=True, errors="coerce")
        df["bucket_dt"] = df["bucket_dt"].dt.tz_convert("Asia/Seoul")
        df = df.dropna(subset=["bucket_dt"]).sort_values("bucket_dt")
        x_field = alt.X(
            "bucket_dt:T",
            title="시간",
            axis=alt.Axis(format="%Y-%m-%d %H:%M"),
        )
        tooltip_bucket = alt.Tooltip("bucket_dt:T", title="시간", format="%Y-%m-%d %H:%M")
    else:
        df["bucket_dt"] = pd.to_datetime(df["bucket"], errors="coerce").dt.date
        df = df.dropna(subset=["bucket_dt"]).sort_values("bucket_dt")
        df["bucket_label"] = df["bucket_dt"].astype(str)
        order = sorted(set(df["bucket_label"].tolist()))
        x_field = alt.X("bucket_label:N", title="날짜", sort=order)
        tooltip_bucket = alt.Tooltip("bucket_label:N", title="날짜")

    if df.empty:
        return

    chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=x_field,
            y=alt.Y("count:Q", title="이벤트 수"),
            tooltip=[tooltip_bucket, alt.Tooltip("count:Q", title="이벤트 수")],
        )
    )
    st.altair_chart(chart, use_container_width=True)


def render_top_actions(summary) -> None:
    if not summary.by_action:
        return
    st.markdown("#### 최다 발생 액션")
    rows = sorted(summary.by_action.items(), key=lambda item: item[1], reverse=True)[:10]
    st.table({"Action": [row[0] for row in rows], "Count": [row[1] for row in rows]})


__all__ = [
    "apply_date_filters",
    "parse_action_tokens",
    "filters_from_state",
    "render_summary_cards",
    "render_activity_chart",
    "render_top_actions",
]

