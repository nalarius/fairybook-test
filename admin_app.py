"""Standalone Streamlit admin console for monitoring and moderation."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import streamlit as st
from dotenv import find_dotenv, load_dotenv


# Load project-level environment variables before importing modules that depend on them
ROOT_ENV = find_dotenv(usecwd=True)
if ROOT_ENV:
    load_dotenv(ROOT_ENV, override=False)
ENV_PATH = Path(__file__).resolve().parent / ".env"
if ENV_PATH.is_file():
    load_dotenv(ENV_PATH, override=False)


from activity_log import init_activity_log, is_activity_logging_enabled, log_event
from admin_tool.auth import (
    admin_display_name,
    admin_email,
    admin_error_message,
    clear_admin_session,
    ensure_active_admin_session,
    store_admin_session,
)
from firebase_auth import FirebaseAuthError, sign_in, verify_id_token
from utils.network import get_client_ip

from admin_ui import dashboard, explorer, moderation, exports


st.set_page_config(page_title="운영자 콘솔", page_icon="🛡️", layout="wide")
init_activity_log()

NAV_KEY = "admin_nav_selection"


def _trigger_rerun() -> None:
    rerun_fn = getattr(st, "rerun", None) or getattr(st, "experimental_rerun", None)
    if callable(rerun_fn):
        rerun_fn()
    else:  # pragma: no cover - fallback for extremely old Streamlit
        st.session_state["_admin_force_rerun"] = st.session_state.get("_admin_force_rerun", 0) + 1


def _log_admin_event(
    action: str,
    result: str,
    *,
    admin_identifier: str | None,
    params: Sequence[str | None] | None = None,
    metadata: Mapping | None = None,
) -> None:
    try:
        log_event(
            type="admin",
            action=action,
            result=result,
            user_id=admin_identifier,
            params=params,
            metadata=metadata,
        )
    except Exception as exc:  # pragma: no cover - logging should not block UI
        st.warning(f"로그 기록에 실패했습니다: {exc}")


def _log_moderation_event(
    action: str,
    result: str,
    *,
    admin_identifier: str | None,
    params: Sequence[str | None],
    metadata: Mapping | None = None,
) -> None:
    try:
        log_event(
            type="moderation",
            action=action,
            result=result,
            user_id=admin_identifier,
            params=params,
            metadata=metadata,
        )
    except Exception as exc:  # pragma: no cover
        st.warning(f"모더레이션 로그 기록 실패: {exc}")


def _render_login() -> None:
    st.title("🛡️ 동화책 생성기 운영자 콘솔")
    st.subheader("관리자 인증")

    if error := admin_error_message():
        st.error(error)

    st.caption("관리자 전용 페이지입니다. 전용 계정으로 로그인해 주세요.")

    with st.form("admin_login_form", clear_on_submit=False):
        email = st.text_input("이메일", placeholder="admin@example.com", max_chars=120, key="admin_login_email")
        password = st.text_input("비밀번호", type="password", key="admin_login_password")
        submitted = st.form_submit_button("로그인", type="primary")

    if not submitted:
        return

    normalized_email = email.strip()
    if not normalized_email or not password:
        st.error("이메일과 비밀번호를 모두 입력해 주세요.")
        return

    client_ip = get_client_ip()

    try:
        session = sign_in(normalized_email, password)
    except FirebaseAuthError as exc:
        st.error(f"Firebase 인증에 실패했어요: {exc} (코드 확인 필요)")
        _log_admin_event(
            "login",
            "fail",
            admin_identifier=normalized_email,
            params=[normalized_email, "signin", client_ip, str(exc), None],
        )
        return
    except Exception as exc:  # pragma: no cover - defensive guard
        st.error(f"로그인을 처리하지 못했어요: {exc}")
        _log_admin_event(
            "login",
            "fail",
            admin_identifier=normalized_email,
            params=[normalized_email, "signin", client_ip, str(exc), None],
        )
        return

    try:
        claims = verify_id_token(session.id_token)
    except Exception as exc:  # pragma: no cover - verification failure
        message = str(exc)
        if "Token used too early" in message:
            time.sleep(2)
            try:
                claims = verify_id_token(session.id_token)
            except Exception as retry_exc:  # pragma: no cover - second failure
                st.error(f"ID 토큰을 검증하는 중 오류가 발생했습니다: {retry_exc}")
                _log_admin_event(
                    "login",
                    "fail",
                    admin_identifier=normalized_email,
                    params=[normalized_email, "verify", client_ip, str(retry_exc), None],
                )
                return
        else:
            st.error(f"ID 토큰을 검증하는 중 오류가 발생했습니다: {exc}")
            _log_admin_event(
                "login",
                "fail",
                admin_identifier=normalized_email,
                params=[normalized_email, "verify", client_ip, str(exc), None],
            )
            return

    if claims.get("role") != "admin":
        st.error("관리자 권한이 없는 계정입니다. 관리자에게 문의해 주세요.")
        _log_admin_event(
            "login",
            "fail",
            admin_identifier=normalized_email,
            params=[normalized_email, "role-check", client_ip, "missing-admin-role", None],
        )
        return

    store_admin_session(session)
    st.session_state["admin_claims"] = claims
    _log_admin_event(
        "login",
        "success",
        admin_identifier=normalized_email,
        params=[normalized_email, "signin", client_ip, None, None],
    )
    st.success("로그인 되었습니다. 콘솔을 준비하고 있어요…")
    st.session_state[NAV_KEY] = "대시보드"
    _trigger_rerun()


def _sidebar(admin_user: Mapping[str, Any]) -> str:
    with st.sidebar:
        st.header("관리자 메뉴")
        st.caption("동화책 생성기 운영 현황을 모니터링하세요.")

        name = admin_display_name(admin_user)
        email = admin_email(admin_user) or "—"
        if name and name.strip() and name != email:
            st.markdown(f"**{name}**\n\n{email}")
        else:
            st.markdown(f"**{email}**")

        if not is_activity_logging_enabled():
            st.warning("활동 로그가 비활성화되어 있어 일부 통계가 최신이 아닐 수 있어요.")

        selection = st.radio(
            "섹션",
            options=(
                "대시보드",
                "사용자 디렉터리",
                "활동 탐색기",
                "내보내기",
            ),
            key=NAV_KEY,
        )

        if st.button("로그아웃", type="secondary"):
            identifier = admin_email(admin_user)
            _log_admin_event(
                "logout",
                "success",
                admin_identifier=identifier,
                params=[identifier, None, None, None, None],
            )
            clear_admin_session()
            _trigger_rerun()

        st.divider()
        st.caption("문제가 있으면 Slack #operations 로 알려주세요.")

    return selection


def _resolve_admin_session() -> tuple[Mapping[str, Any] | None, Mapping | None]:
    session_state = ensure_active_admin_session()
    if not session_state:
        return None, None

    claims = st.session_state.get("admin_claims")
    if not isinstance(claims, Mapping):
        try:
            claims = verify_id_token(str(session_state.get("id_token")))
        except Exception:  # pragma: no cover
            claims = {}
        st.session_state["admin_claims"] = claims
    return session_state, claims


def main() -> None:
    admin_session, _claims = _resolve_admin_session()
    if not admin_session:
        _render_login()
        return

    section = _sidebar(admin_session)

    if section == "대시보드":
        dashboard.render_dashboard(admin_session)
    elif section == "사용자 디렉터리":
        moderation.render_user_directory(
            admin_session,
            log_admin_event=_log_admin_event,
            log_moderation_event=_log_moderation_event,
            trigger_rerun=_trigger_rerun,
            admin_email_lookup=admin_email,
        )
    elif section == "활동 탐색기":
        explorer.render_activity_explorer(admin_session, _trigger_rerun)
    else:
        exports.render_exports(
            admin_session,
            log_admin_event=_log_admin_event,
            admin_email_lookup=admin_email,
        )


if __name__ == "__main__":
    main()
