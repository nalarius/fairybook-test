"""Activity explorer view for the admin console."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable, Mapping, Sequence

import streamlit as st

from admin_tool.activity_service import entry_to_row, fetch_activity_page
from admin_tool.constants import DEFAULT_PAGE_SIZE

from . import common


ACTIVITY_FILTER_STATE_KEY = "admin_activity_filters"
ACTIVITY_CURSOR_KEY = "admin_activity_cursor"
EVENT_TYPE_OPTIONS = ("story", "user", "board", "moderation", "admin")
RESULT_OPTIONS = ("success", "fail")


def _serialize_activity_page(entries: Sequence[Any]) -> list[dict[str, Any]]:
    return [entry_to_row(entry) for entry in entries]


def _render_activity_table(entries: Sequence[Any]) -> None:
    rows = _serialize_activity_page(entries)
    if not rows:
        st.info("표시할 로그가 없습니다.")
        return
    if common.pd:
        st.dataframe(common.pd.DataFrame(rows))
    else:  # pragma: no cover - fallback rendering
        st.json(rows)


def render_activity_explorer(admin_user: Mapping[str, Any], trigger_rerun: Callable[[], None]) -> None:
    st.title("🔍 활동 탐색기")
    state = st.session_state.setdefault(
        ACTIVITY_FILTER_STATE_KEY,
        {
            "start_date": date.today() - timedelta(days=7),
            "end_date": date.today(),
            "types": list(EVENT_TYPE_OPTIONS),
            "results": list(RESULT_OPTIONS),
            "actions": [],
        },
    )

    with st.form("activity_filters"):
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
            "액션 필터 (쉼표로 구분)",
            value=", ".join(state.get("actions", [])),
        )
        page_size = st.slider("한 번에 불러올 로그 수", 20, 200, DEFAULT_PAGE_SIZE)
        submitted = st.form_submit_button("필터 적용", type="primary")

    if isinstance(start_end, tuple) and len(start_end) == 2:
        state["start_date"], state["end_date"] = start_end

    if submitted:
        state["types"] = list(selected_types)
        state["results"] = list(selected_results)
        state["actions"] = list(common.parse_action_tokens(action_tokens))
        st.session_state[ACTIVITY_CURSOR_KEY] = None

    filters = common.filters_from_state(state)
    cursor = st.session_state.get(ACTIVITY_CURSOR_KEY)
    page = fetch_activity_page(filters, cursor=cursor, limit=page_size)

    _render_activity_table(page.entries)

    buttons = st.columns(3)
    if buttons[0].button("처음부터", disabled=cursor is None):
        st.session_state[ACTIVITY_CURSOR_KEY] = None
        trigger_rerun()
    if page.has_more and page.next_cursor:
        if buttons[2].button("더 보기"):
            st.session_state[ACTIVITY_CURSOR_KEY] = page.next_cursor
            trigger_rerun()


__all__ = ["render_activity_explorer"]
