"""Account settings view for updating user profile details."""
from __future__ import annotations

from typing import Mapping

import streamlit as st

from firebase_auth import delete_account, update_password, update_profile
from telemetry import emit_log_event
from ui.styles import render_app_styles
from utils.auth import (
    auth_display_name,
    auth_email,
    clear_auth_session,
    format_auth_error,
    store_auth_session,
)
from utils.network import get_client_ip
from session_state import reset_all_state


def _ensure_display_name_seed(auth_user: Mapping[str, object] | None) -> None:
    if "settings_display_name_input" in st.session_state:
        return
    current = str(auth_user.get("display_name") or "") if auth_user else ""
    if not current:
        current = str(auth_user.get("email") or "") if auth_user else ""
    st.session_state["settings_display_name_input"] = current


def render_account_settings(home_bg: str | None, *, auth_user: Mapping[str, object] | None) -> None:
    render_app_styles(home_bg, show_home_hero=False)
    st.subheader("⚙️ 계정 설정")

    if not auth_user:
        st.warning("로그인 후에 계정 설정을 이용할 수 있습니다.")
        if st.button("← 돌아가기", use_container_width=True):
            reset_all_state()
            st.rerun()
        st.stop()

    if st.button("← 메뉴로 돌아가기", use_container_width=True):
        st.session_state["mode"] = None
        st.session_state["auth_next_action"] = None
        st.session_state["step"] = 0
        st.rerun()

    st.markdown("---")

    id_token = str(auth_user.get("id_token") or "")
    if not id_token:
        st.error("계정 토큰을 찾지 못했습니다. 다시 로그인해 주세요.")
        return

    client_ip = get_client_ip()

    # Display name ----------------------------------------------------------------
    _ensure_display_name_seed(auth_user)
    st.markdown("### 표시 이름 변경")
    st.caption("게시판과 서비스 전반에서 보여질 이름을 바꿉니다.")
    with st.form("display_name_form", clear_on_submit=False):
        st.text_input(
            "새 표시 이름",
            key="settings_display_name_input",
            max_chars=40,
            help="2자 이상 입력해 주세요.",
        )
        display_submitted = st.form_submit_button("변경 저장", use_container_width=True, type="primary")

    if display_submitted:
        desired = (st.session_state.get("settings_display_name_input") or "").strip()
        current_display = auth_display_name(auth_user)
        if not desired:
            st.warning("표시 이름을 입력해 주세요.")
        elif desired == current_display:
            st.info("현재 표시 이름과 동일합니다.")
        else:
            try:
                session = update_profile(id_token, display_name=desired)
            except Exception as exc:  # noqa: BLE001
                st.error(format_auth_error(exc))
                emit_log_event(
                    type="user",
                    action="profile update",
                    result="fail",
                    params=[client_ip, desired, "display_name", None, str(exc)],
                    client_ip=client_ip,
                )
            else:
                store_auth_session(session, previous=auth_user)
                auth_user = st.session_state.get("auth_user") or auth_user
                id_token = str(auth_user.get("id_token") or id_token)
                if desired:
                    st.session_state["board_user_alias"] = desired
                st.success("표시 이름을 변경했습니다.")
                emit_log_event(
                    type="user",
                    action="profile update",
                    result="success",
                    params=[client_ip, desired, "display_name", None, None],
                    client_ip=client_ip,
                )

    st.markdown("---")

    # Password --------------------------------------------------------------------
    st.markdown("### 비밀번호 변경")
    st.caption("6자 이상 새 비밀번호를 입력해 주세요.")
    with st.form("password_change_form", clear_on_submit=True):
        new_password = st.text_input("새 비밀번호", type="password", key="settings_new_password")
        confirm_password = st.text_input("새 비밀번호 확인", type="password", key="settings_confirm_password")
        password_submitted = st.form_submit_button("비밀번호 변경", use_container_width=True, type="primary")

    if password_submitted:
        new_password = new_password.strip()
        confirm_password = confirm_password.strip()
        if not new_password or not confirm_password:
            st.warning("새 비밀번호를 모두 입력해 주세요.")
        elif len(new_password) < 6:
            st.warning("비밀번호는 6자 이상이어야 합니다.")
        elif new_password != confirm_password:
            st.warning("비밀번호 확인 값이 일치하지 않습니다.")
        else:
            try:
                session = update_password(id_token, new_password=new_password)
            except Exception as exc:  # noqa: BLE001
                st.error(format_auth_error(exc))
                emit_log_event(
                    type="user",
                    action="password change",
                    result="fail",
                    params=[client_ip, auth_email(auth_user), None, None, str(exc)],
                    client_ip=client_ip,
                )
            else:
                store_auth_session(session, previous=auth_user)
                auth_user = st.session_state.get("auth_user") or auth_user
                id_token = str(auth_user.get("id_token") or id_token)
                st.success("비밀번호를 변경했습니다.")
                emit_log_event(
                    type="user",
                    action="password change",
                    result="success",
                    params=[client_ip, auth_email(auth_user), None, None, None],
                    client_ip=client_ip,
                )

    st.markdown("---")

    # Account deletion -------------------------------------------------------------
    st.markdown("### 계정 삭제")
    st.warning(
        "계정을 삭제하면 동화 기록과 게시판에서 사용된 이름이 더 이상 복구되지 않습니다. "
        "정말로 탈퇴하려면 아래에 이메일 주소를 입력하고 버튼을 눌러 주세요.",
    )
    with st.form("account_delete_form", clear_on_submit=True):
        confirm_label = auth_email(auth_user) or ""
        confirm_input = st.text_input(
            "이메일 확인",
            placeholder=confirm_label,
            key="settings_delete_confirm",
        )
        confirm = st.form_submit_button(
            "계정 완전히 삭제하기",
            use_container_width=True,
            type="primary",
        )

    if confirm:
        expected = confirm_label.strip()
        provided = confirm_input.strip()
        if not expected:
            st.error("이메일 정보를 확인할 수 없습니다. 다시 로그인 후 시도해 주세요.")
        elif provided != expected:
            st.warning("입력한 이메일이 계정과 일치하지 않습니다.")
        else:
            try:
                delete_account(id_token)
            except Exception as exc:  # noqa: BLE001
                st.error(format_auth_error(exc))
                emit_log_event(
                    type="user",
                    action="account delete",
                    result="fail",
                    params=[client_ip, expected, None, None, str(exc)],
                    client_ip=client_ip,
                )
            else:
                emit_log_event(
                    type="user",
                    action="account delete",
                    result="success",
                    params=[client_ip, expected, None, None, None],
                    client_ip=client_ip,
                )
                clear_auth_session()
                reset_all_state()
                st.session_state["board_user_alias"] = None
                st.session_state["board_content"] = ""
                st.session_state["auth_next_action"] = None
                st.success("계정을 삭제했습니다. 이용해 주셔서 감사합니다.")
                st.rerun()


__all__ = ["render_account_settings"]
