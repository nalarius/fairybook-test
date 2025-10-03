"""Moderation and user management views."""
from __future__ import annotations

from typing import Any, Callable, Mapping

import streamlit as st

from admin_tool.constants import MODERATION_REASON_CODES, SANCTION_DURATION_PRESETS
from admin_tool.user_service import (
    AdminUser,
    apply_user_sanction,
    generate_password_reset,
    list_users,
    set_user_disabled,
    set_user_role,
)
from firebase_auth import FirebaseAuthError


def _render_user_card(
    user: AdminUser,
    *,
    administrator: Mapping[str, Any],
    log_admin_event: Callable[..., None],
    log_moderation_event: Callable[..., None],
    trigger_rerun: Callable[[], None],
    admin_email_lookup: Callable[[Mapping[str, Any]], str | None],
) -> None:
    with st.expander(f"{user.email or user.uid}"):
        cols = st.columns(4)
        cols[0].write(f"UID: {user.uid}")
        cols[1].write(f"상태: {'비활성화' if user.disabled else '활성'}")
        cols[2].write(f"역할: {user.role or '미지정'}")
        cols[3].write(f"최근 로그인: {user.last_sign_in.isoformat() if user.last_sign_in else '—'}")

        action_cols = st.columns(3)
        toggle_label = "재활성화" if user.disabled else "사용 중지"
        if action_cols[0].button(toggle_label, key=f"toggle-{user.uid}"):
            try:
                updated = set_user_disabled(user.uid, not user.disabled)
            except FirebaseAuthError as exc:  # pragma: no cover
                st.error(f"상태를 변경하지 못했어요: {exc}")
            else:
                identifier = admin_email_lookup(administrator)
                log_admin_event(
                    "user disable" if updated.disabled else "user enable",
                    "success",
                    admin_identifier=identifier,
                    params=[user.uid, toggle_label, None, None, None],
                )
                st.success("변경되었습니다.")
                trigger_rerun()

        if user.email and action_cols[1].button("재설정 링크", key=f"reset-{user.uid}"):
            try:
                link = generate_password_reset(user.email)
            except Exception as exc:  # pragma: no cover
                st.error(f"재설정 링크를 생성하지 못했어요: {exc}")
            else:
                identifier = admin_email_lookup(administrator)
                log_admin_event(
                    "password reset",
                    "success",
                    admin_identifier=identifier,
                    params=[user.uid, user.email, link, None, None],
                )
                st.info(f"재설정 링크가 생성되었습니다: {link}")

        with st.form(f"role-form-{user.uid}"):
            selected_role = st.selectbox(
                "역할",
                options=("", "support", "admin"),
                index=(0 if not user.role else (2 if user.role == "admin" else 1)),
                help="빈 값으로 선택하면 역할을 제거합니다.",
            )
            if st.form_submit_button("역할 업데이트"):
                try:
                    updated = set_user_role(user.uid, selected_role or None)
                except Exception as exc:  # pragma: no cover
                    st.error(f"역할을 변경하지 못했어요: {exc}")
                else:
                    identifier = admin_email_lookup(administrator)
                    log_admin_event(
                        "role promote" if updated.role else "role clear",
                        "success",
                        admin_identifier=identifier,
                        params=[user.uid, selected_role or "none", None, None, None],
                    )
                    st.success("역할이 변경되었습니다.")
                    trigger_rerun()

        st.markdown("#### 제재 적용")
        with st.form(f"sanction-form-{user.uid}"):
            sanction_type = st.selectbox("제재 유형", options=("ban", "mute", "unban"))
            duration = st.selectbox("지속 시간", options=SANCTION_DURATION_PRESETS)
            reason = st.selectbox("사유", options=MODERATION_REASON_CODES)
            target_context = st.text_input("관련 ID (게시글/스토리 등)")
            note = st.text_area("메모 (최대 280자)", max_chars=280)
            submitted = st.form_submit_button("제재 적용")

        if submitted:
            identifier = admin_email_lookup(administrator)
            try:
                updated, sanction_payload = apply_user_sanction(
                    user.uid,
                    sanction_type=sanction_type,
                    duration=duration,
                    reason=reason,
                    note=note,
                    context_id=target_context or None,
                    applied_by=identifier,
                )
            except Exception as exc:  # pragma: no cover
                st.error(f"제재 적용에 실패했어요: {exc}")
                log_moderation_event(
                    "user sanction",
                    "fail",
                    admin_identifier=identifier,
                    params=[user.uid, sanction_type, duration, note, target_context],
                    metadata={"error": str(exc)},
                )
            else:
                st.success("제재 정보가 업데이트되었습니다.")
                log_moderation_event(
                    "user sanction" if sanction_type != "unban" else "user sanction clear",
                    "success",
                    admin_identifier=identifier,
                    params=[
                        user.uid,
                        sanction_type,
                        duration,
                        note,
                        target_context,
                    ],
                    metadata=sanction_payload,
                )
                trigger_rerun()

        if user.sanction:
            st.info(f"현재 제재 상태: {user.sanction}")


def render_user_directory(
    admin_user: Mapping[str, Any],
    *,
    log_admin_event: Callable[..., None],
    log_moderation_event: Callable[..., None],
    trigger_rerun: Callable[[], None],
    admin_email_lookup: Callable[[Mapping[str, Any]], str | None],
) -> None:
    st.title("👥 사용자 디렉터리")
    state = st.session_state.setdefault(
        USER_SEARCH_STATE_KEY,
        {
            "query": "",
            "role": "all",
        },
    )

    with st.form("user_search_form"):
        query = st.text_input("이메일/UID 검색", value=state.get("query", ""))
        role_filter = st.selectbox("역할", options=("all", "admin", "support", "none"), index=0)
        submitted = st.form_submit_button("검색", type="primary")

    if submitted:
        state["query"] = query
        state["role"] = role_filter

    try:
        users, _next_token = list_users(query=state.get("query") or None, role=state.get("role"))
    except Exception as exc:  # pragma: no cover
        st.error(f"사용자 목록을 가져오지 못했습니다: {exc}")
        return

    if not users:
        st.info("조건에 맞는 사용자가 없습니다.")
        return

    st.caption(f"총 {len(users)}명")
    for user in users:
        _render_user_card(
            user,
            administrator=admin_user,
            log_admin_event=log_admin_event,
            log_moderation_event=log_moderation_event,
            trigger_rerun=trigger_rerun,
            admin_email_lookup=admin_email_lookup,
        )


__all__ = ["render_user_directory"]

USER_SEARCH_STATE_KEY = "admin_user_directory_state"
