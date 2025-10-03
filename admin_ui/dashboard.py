"""Dashboard view for the admin console."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Mapping

import streamlit as st

from admin_tool.activity_service import gather_activity_entries, summarize_entries
from admin_tool.constants import DEFAULT_DASHBOARD_RANGE_DAYS, DEFAULT_PAGE_SIZE

DASHBOARD_STATE_KEY = "admin_dashboard_filters"
EVENT_TYPE_OPTIONS = ("story", "user", "board", "moderation", "admin")
RESULT_OPTIONS = ("success", "fail")

from . import common


def render_dashboard(admin_user: Mapping[str, Any]) -> None:
    st.title("📊 사용량 대시보드")
    state = st.session_state.setdefault(
        DASHBOARD_STATE_KEY,
        {
            "start_date": date.today() - timedelta(days=DEFAULT_DASHBOARD_RANGE_DAYS),
            "end_date": date.today(),
            "types": list(EVENT_TYPE_OPTIONS),
            "results": list(RESULT_OPTIONS),
            "actions": [],
            "granularity": "hourly",
        },
    )

    with st.form("dashboard_filters"):
        start_end = st.date_input(
            "조회 기간",
            value=(state["start_date"], state["end_date"]),
            max_value=date.today(),
        )
        selected_types = st.multiselect(
            "이벤트 유형",
            options=EVENT_TYPE_OPTIONS,
            default=state.get("types", EVENT_TYPE_OPTIONS),
        )
        selected_results = st.multiselect(
            "결과",
            options=RESULT_OPTIONS,
            default=state.get("results", RESULT_OPTIONS),
        )
        action_tokens = st.text_input(
            "특정 액션 필터 (쉼표로 구분)",
            value=", ".join(state.get("actions", [])),
        )
        submitted = st.form_submit_button("필터 적용", type="primary")

    if isinstance(start_end, tuple) and len(start_end) == 2:
        state["start_date"], state["end_date"] = start_end

    if submitted:
        state["types"] = list(selected_types)
        state["results"] = list(selected_results)
        state["actions"] = list(common.parse_action_tokens(action_tokens))

    filters = common.filters_from_state(state)
    entries = gather_activity_entries(filters, max_records=DEFAULT_PAGE_SIZE * 5)

    if not entries:
        st.info("선택한 조건에 해당하는 로그가 없습니다.")
        return

    summary = summarize_entries(entries)
    common.render_summary_cards(summary)
    granularity = state.get("granularity", "hourly")
    radio_key = "dashboard_granularity"
    if radio_key not in st.session_state:
        st.session_state[radio_key] = granularity
    granularity = st.radio(
        "그래프 단위",
        options=("hourly", "daily"),
        index=0 if granularity == "hourly" else 1,
        format_func=lambda value: "시간별" if value == "hourly" else "일별",
        horizontal=True,
        key=radio_key,
    )
    if granularity != state.get("granularity"):
        state["granularity"] = granularity
    common.render_activity_chart(summary, granularity)
    common.render_top_actions(summary)
