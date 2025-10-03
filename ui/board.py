"""Community board UI separated from the main Streamlit app."""
from __future__ import annotations

from typing import Mapping

import streamlit as st

from community_board import BoardPost, add_post, init_board_store, list_posts
from telemetry import emit_log_event
from ui.styles import render_app_styles
from utils.auth import auth_display_name
from utils.network import get_client_ip, mask_client_ip
from utils.time_utils import format_kst

BOARD_POST_LIMIT = 50


def render_board_page(home_bg: str | None, *, auth_user: Mapping[str, object]) -> None:
    """Render the lightweight community board view."""
    init_board_store()
    render_app_styles(home_bg, show_home_hero=False)

    current_ip = get_client_ip()
    if not st.session_state.get("board_view_logged"):
        emit_log_event(
            type="board",
            action="board read",
            result="success",
            params=[current_ip, auth_display_name(auth_user) if auth_user else None, None, None, None],
            client_ip=current_ip,
        )
        st.session_state["board_view_logged"] = True

    st.subheader("💬 동화 작업실 게시판")
    st.caption("동화를 만드는 분들끼리 짧은 메모를 나누는 공간이에요. 친절한 응원과 진행 상황을 가볍게 남겨보세요.")

    default_alias = st.session_state.get("board_user_alias") or auth_display_name(auth_user)
    st.session_state.setdefault("board_user_alias", default_alias)

    if st.button("← 홈으로 돌아가기", width='stretch'):
        st.session_state["mode"] = None
        st.session_state["step"] = 0
        st.session_state["board_submit_error"] = None
        st.session_state["board_submit_success"] = None
        st.session_state["board_view_logged"] = False
        st.rerun()
        st.stop()

    st.markdown("---")

    with st.form("board_form", clear_on_submit=False):
        alias_display = st.session_state.get("board_user_alias", default_alias)
        st.markdown(f"**게시판에서 표시할 이름:** {alias_display}")
        content_value = st.text_area(
            "메시지",
            value=st.session_state.get("board_content", ""),
            height=140,
            max_chars=1000,
            placeholder="동화 작업 중 느낀 점이나 부탁할 내용을 자유롭게 남겨주세요.",
        )
        submitted = st.form_submit_button("메시지 남기기", type="primary", width='stretch')

    alias_value = default_alias
    st.session_state["board_user_alias"] = alias_value
    st.session_state["board_content"] = content_value

    if submitted:
        try:
            client_ip = current_ip or get_client_ip()
            post_id = add_post(
                user_id=alias_value or auth_display_name(auth_user),
                content=content_value,
                client_ip=client_ip,
            )
        except ValueError as exc:
            message = str(exc)
            st.session_state["board_submit_error"] = message
            emit_log_event(
                type="board",
                action="board post",
                result="fail",
                params=[None, alias_value or auth_display_name(auth_user), None, None, message],
                client_ip=client_ip,
            )
        except Exception as exc:  # noqa: BLE001
            message = "메시지를 저장하지 못했어요. 잠시 후 다시 시도해 주세요."
            st.session_state["board_submit_error"] = message
            emit_log_event(
                type="board",
                action="board post",
                result="fail",
                params=[None, alias_value or auth_display_name(auth_user), None, None, str(exc)],
                client_ip=client_ip,
            )
        else:
            st.session_state["board_content"] = ""
            st.session_state["board_submit_error"] = None
            st.session_state["board_submit_success"] = "메시지를 남겼어요!"
            emit_log_event(
                type="board",
                action="board post",
                result="success",
                params=[post_id, alias_value or auth_display_name(auth_user), None, None, None],
                client_ip=client_ip,
            )
            st.rerun()
            st.stop()

    if st.session_state.get("board_submit_error"):
        st.error(st.session_state["board_submit_error"])
        st.session_state["board_submit_error"] = None
    elif st.session_state.get("board_submit_success"):
        st.success(st.session_state["board_submit_success"])
        st.session_state["board_submit_success"] = None

    posts: list[BoardPost] = list_posts(limit=BOARD_POST_LIMIT)
    if not posts:
        st.info("아직 작성된 메시지가 없어요. 첫 글을 남겨보세요!")
        return

    st.markdown("---")
    for post in posts:
        masked_ip = mask_client_ip(post.client_ip)
        timestamp = format_kst(post.created_at_utc)
        meta = f"{timestamp} · {masked_ip}"
        st.markdown(f"**{post.user_id}** · {meta}")
        st.write(post.content)
        st.markdown("---")


__all__ = ["render_board_page", "BOARD_POST_LIMIT"]
