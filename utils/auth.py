"""Authentication state helpers shared across UI components."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import streamlit as st

from firebase_auth import AuthSession, FirebaseAuthError, refresh_id_token

_TOKEN_REFRESH_LEEWAY = timedelta(minutes=2)


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def store_auth_session(session: AuthSession, *, previous: Mapping[str, Any] | None = None) -> None:
    prev = dict(previous) if previous else {}

    email = session.email or prev.get("email", "")
    display_name = session.display_name or prev.get("display_name", "")
    uid = session.uid or prev.get("uid", "")
    refresh_token = session.refresh_token or prev.get("refresh_token", "")

    st.session_state["auth_user"] = {
        "uid": uid,
        "email": email,
        "display_name": display_name,
        "id_token": session.id_token or prev.get("id_token", ""),
        "refresh_token": refresh_token,
        "expires_at": session.expires_at.isoformat(),
        "is_email_verified": session.is_email_verified or bool(prev.get("is_email_verified")),
    }
    st.session_state["auth_error"] = None

    if prev.get("uid") != uid:
        st.session_state["board_content"] = ""
        st.session_state["board_user_alias"] = display_name or email
    else:
        st.session_state.setdefault("board_content", "")
        st.session_state.setdefault("board_user_alias", display_name or email)


def clear_auth_session() -> None:
    st.session_state["auth_user"] = None
    st.session_state["auth_error"] = None
    st.session_state["auth_form_mode"] = "signin"


def auth_user_from_state() -> dict[str, Any] | None:
    raw = st.session_state.get("auth_user")
    if not isinstance(raw, Mapping):
        return None

    data = dict(raw)
    expires_at = parse_iso_datetime(data.get("expires_at"))
    refresh_token = data.get("refresh_token")
    id_token = data.get("id_token")

    if not expires_at or not refresh_token or not id_token:
        clear_auth_session()
        return None

    data["expires_at"] = expires_at
    return data


def format_auth_error(error: Exception) -> str:
    if isinstance(error, FirebaseAuthError):
        code = (error.code or "").upper()
        messages = {
            "EMAIL_EXISTS": "이미 가입된 이메일이에요. 로그인으로 이동해 주세요.",
            "INVALID_PASSWORD": "비밀번호가 올바르지 않습니다.",
            "USER_NOT_FOUND": "등록되지 않은 이메일입니다.",
            "INVALID_EMAIL": "이메일 주소 형식을 확인해 주세요.",
            "WEAK_PASSWORD": "비밀번호는 6자 이상이어야 합니다.",
            "MISSING_PASSWORD": "비밀번호를 입력해 주세요.",
        }
        if code in messages:
            return messages[code]
        return "Firebase 인증 요청이 실패했어요. 잠시 후 다시 시도해 주세요."
    if isinstance(error, RuntimeError):
        return str(error)
    return "인증을 처리하는 중 오류가 발생했어요."


def ensure_active_auth_session() -> dict[str, Any] | None:
    user = auth_user_from_state()
    if not user:
        return None

    expires_at: datetime = user["expires_at"]
    now = datetime.now(timezone.utc)
    if expires_at <= now:
        refresh_needed = True
    else:
        refresh_needed = (expires_at - now) <= _TOKEN_REFRESH_LEEWAY

    if refresh_needed:
        refresh_token = user.get("refresh_token")
        if refresh_token:
            try:
                refreshed = refresh_id_token(refresh_token)
            except FirebaseAuthError as exc:
                st.session_state["auth_error"] = format_auth_error(exc)
                clear_auth_session()
                return None
            except Exception as exc:  # pragma: no cover - defensive
                st.session_state["auth_error"] = f"세션을 갱신하지 못했어요: {exc}"
                clear_auth_session()
                return None
            else:
                store_auth_session(refreshed, previous=user)
                user = auth_user_from_state()
        else:
            clear_auth_session()
            return None

    return user


def auth_display_name(user: Mapping[str, Any]) -> str:
    display = str(user.get("display_name") or "").strip()
    email = str(user.get("email") or "").strip()
    return display or email or "익명 사용자"


def auth_email(user: Mapping[str, Any] | None) -> str | None:
    if not user:
        return None
    email = str(user.get("email") or "").strip()
    return email or None


__all__ = [
    "parse_iso_datetime",
    "store_auth_session",
    "clear_auth_session",
    "auth_user_from_state",
    "format_auth_error",
    "ensure_active_auth_session",
    "auth_display_name",
    "auth_email",
]
