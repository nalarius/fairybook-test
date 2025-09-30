"""Authentication views for the Streamlit application."""
from __future__ import annotations

import streamlit as st

from firebase_auth import sign_in, sign_up, update_profile
from telemetry import emit_log_event
from ui.styles import render_app_styles
from utils.auth import auth_display_name, format_auth_error, store_auth_session
from utils.network import get_client_ip


def _handle_post_auth_redirect() -> None:
    next_action = st.session_state.pop("auth_next_action", None)
    st.session_state["auth_error"] = None

    if next_action == "create":
        st.session_state["mode"] = "create"
        st.session_state["step"] = max(1, st.session_state.get("step", 0))
    elif next_action == "board":
        st.session_state["mode"] = "board"
        st.session_state["step"] = 0
    else:
        st.session_state["mode"] = None
        st.session_state["step"] = 0

    st.rerun()


def render_auth_gate(home_bg: str | None) -> None:
    render_app_styles(home_bg, show_home_hero=True)
    st.title("📖 동화책 생성기")
    st.subheader("먼저 로그인해 주세요")

    if st.session_state.get("auth_error"):
        st.error(st.session_state["auth_error"])

    if st.session_state.get("auth_next_action") == "create":
        st.caption("동화 만들기를 계속하려면 로그인해주세요.")
    elif st.session_state.get("auth_next_action") == "board":
        st.caption("게시판을 이용하려면 로그인해주세요.")

    if st.button("← 돌아가기", type="secondary"):
        st.session_state["mode"] = None
        st.session_state["step"] = 0
        st.session_state["auth_error"] = None
        st.session_state["auth_next_action"] = None
        st.rerun()

    mode = st.radio(
        "계정이 있으신가요?",
        options=("signin", "signup"),
        format_func=lambda value: "로그인" if value == "signin" else "회원가입",
        horizontal=True,
        key="auth_form_mode",
    )

    if mode == "signin":
        with st.form("auth_signin_form", clear_on_submit=True):
            email = st.text_input(
                "이메일",
                key="auth_signin_email",
                placeholder="예: fairy@storybook.com",
                max_chars=120,
            )
            password = st.text_input(
                "비밀번호",
                type="password",
                key="auth_signin_password",
            )
            submitted = st.form_submit_button("로그인", type="primary", width='stretch')

        if submitted:
            email_norm = email.strip()
            if not email_norm or not password:
                st.session_state["auth_error"] = "이메일과 비밀번호를 모두 입력해 주세요."
            else:
                client_ip = get_client_ip()
                try:
                    session = sign_in(email_norm, password)
                except Exception as exc:  # noqa: BLE001
                    message = format_auth_error(exc)
                    st.session_state["auth_error"] = message
                    emit_log_event(
                        type="user",
                        action="login",
                        result="fail",
                        user_email=email_norm,
                        params=[client_ip, email_norm, None, None, message],
                        client_ip=client_ip,
                    )
                else:
                    store_auth_session(session)
                    current_user = st.session_state.get("auth_user") or {}
                    emit_log_event(
                        type="user",
                        action="login",
                        result="success",
                        params=[
                            client_ip,
                            auth_display_name(current_user),
                            None,
                            None,
                            None,
                        ],
                        client_ip=client_ip,
                    )
                    _handle_post_auth_redirect()
    else:
        with st.form("auth_signup_form", clear_on_submit=True):
            display_name = st.text_input(
                "표시 이름",
                key="auth_signup_display_name",
                placeholder="게시판에 보일 이름",
                max_chars=40,
            )
            email = st.text_input(
                "이메일",
                key="auth_signup_email",
                placeholder="예: fairy@storybook.com",
                max_chars=120,
            )
            password = st.text_input(
                "비밀번호 (6자 이상)",
                type="password",
                key="auth_signup_password",
            )
            submitted = st.form_submit_button("가입하기", type="primary", width='stretch')

        if submitted:
            email_norm = email.strip()
            display_norm = display_name.strip()
            if not email_norm or not password:
                st.session_state["auth_error"] = "이메일과 비밀번호를 입력해 주세요."
            else:
                client_ip = get_client_ip()
                try:
                    session = sign_up(email_norm, password, display_name=display_norm or None)
                    if display_norm and not session.display_name:
                        session = update_profile(session.id_token, display_name=display_norm)
                except Exception as exc:  # noqa: BLE001
                    message = format_auth_error(exc)
                    st.session_state["auth_error"] = message
                    emit_log_event(
                        type="user",
                        action="signup",
                        result="fail",
                        user_email=email_norm,
                        params=[client_ip, display_norm or email_norm, None, None, message],
                        client_ip=client_ip,
                    )
                else:
                    store_auth_session(session)
                    current_user = st.session_state.get("auth_user") or {}
                    emit_log_event(
                        type="user",
                        action="signup",
                        result="success",
                        params=[
                            client_ip,
                            auth_display_name(current_user),
                            None,
                            None,
                            None,
                        ],
                        client_ip=client_ip,
                    )
                    _handle_post_auth_redirect()

    st.caption("로그인에 어려움이 있다면 관리자에게 문의해 주세요.")


__all__ = ["render_auth_gate"]
