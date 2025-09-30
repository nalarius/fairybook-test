"""Home screen for selecting the app mode."""
from __future__ import annotations

from typing import Mapping, Sequence

import streamlit as st

from gcs_storage import is_gcs_available, list_gcs_exports
from services.story_service import list_html_exports
from story_library import list_story_records
from session_state import ensure_state, reset_all_state

def render_home_screen(
    *,
    auth_user: Mapping[str, object] | None,
    use_remote_exports: bool,
    story_types: Sequence[Mapping[str, object]],
) -> None:
    st.subheader("어떤 작업을 하시겠어요?")
    try:
        exports_available = bool(list_story_records(limit=1))
    except Exception:
        if use_remote_exports and is_gcs_available():
            exports_available = bool(list_gcs_exports())
        else:
            exports_available = bool(list_html_exports())

    c1, c2 = st.columns(2)
    with c1:
        if st.button("✏️ 동화 만들기", width='stretch'):
            if auth_user:
                reset_all_state()
                ensure_state(story_types)
                st.session_state["mode"] = "create"
                st.session_state["step"] = 1
            else:
                st.session_state["auth_next_action"] = "create"
                st.session_state["mode"] = "auth"
            st.rerun()
    with c2:
        view_clicked = st.button(
            "📖 동화책 읽기",
            width='stretch',
            disabled=not exports_available,
        )
        if view_clicked:
            st.session_state["mode"] = "view"
            st.session_state["step"] = 5

    board_clicked = st.button("💬 동화 작업실 게시판", width='stretch')
    if board_clicked:
        if auth_user:
            st.session_state["mode"] = "board"
            st.session_state["step"] = 0
            st.session_state["board_submit_error"] = None
            st.session_state["board_submit_success"] = None
        else:
            st.session_state["auth_next_action"] = "board"
            st.session_state["mode"] = "auth"
        st.rerun()


__all__ = ["render_home_screen"]
