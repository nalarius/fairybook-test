"""Admin-specific authentication helpers that mirror user session utilities."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import streamlit as st

from firebase_auth import AuthSession, FirebaseAuthError, refresh_id_token

_ADMIN_SESSION_KEY = "admin_auth_user"
_ADMIN_ERROR_KEY = "admin_auth_error"
_ADMIN_TOKEN_LEEWAY = timedelta(minutes=2)


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def store_admin_session(session: AuthSession, *, previous: Mapping[str, Any] | None = None) -> None:
    """Persist the authenticated admin session inside Streamlit state."""

    prev = dict(previous) if previous else {}

    payload = {
        "uid": session.uid or prev.get("uid", ""),
        "email": session.email or prev.get("email", ""),
        "display_name": session.display_name or prev.get("display_name", ""),
        "id_token": session.id_token or prev.get("id_token", ""),
        "refresh_token": session.refresh_token or prev.get("refresh_token", ""),
        "expires_at": session.expires_at.isoformat(),
    }

    st.session_state[_ADMIN_SESSION_KEY] = payload
    st.session_state[_ADMIN_ERROR_KEY] = None


def clear_admin_session() -> None:
    st.session_state[_ADMIN_SESSION_KEY] = None
    st.session_state[_ADMIN_ERROR_KEY] = None
    st.session_state.pop("admin_claims", None)


def admin_session_from_state() -> dict[str, Any] | None:
    raw = st.session_state.get(_ADMIN_SESSION_KEY)
    if not isinstance(raw, Mapping):
        return None

    data = dict(raw)
    expires_at = _parse_iso_datetime(data.get("expires_at"))
    if not expires_at:
        clear_admin_session()
        return None

    refresh_token = str(data.get("refresh_token") or "")
    id_token = str(data.get("id_token") or "")
    if not refresh_token or not id_token:
        clear_admin_session()
        return None

    data["expires_at"] = expires_at
    return data


def ensure_active_admin_session() -> dict[str, Any] | None:
    """Return a fresh admin session, refreshing the ID token when needed."""

    user = admin_session_from_state()
    if not user:
        return None

    expires_at: datetime = user["expires_at"]
    now = datetime.now(timezone.utc)
    needs_refresh = expires_at <= now or (expires_at - now) <= _ADMIN_TOKEN_LEEWAY

    if needs_refresh:
        refresh_token = str(user.get("refresh_token") or "")
        if not refresh_token:
            clear_admin_session()
            return None
        try:
            refreshed = refresh_id_token(refresh_token)
        except FirebaseAuthError as exc:
            clear_admin_session()
            st.session_state[_ADMIN_ERROR_KEY] = str(exc)
            return None
        except Exception as exc:  # pragma: no cover - defensive
            clear_admin_session()
            st.session_state[_ADMIN_ERROR_KEY] = f"세션을 갱신하지 못했어요: {exc}"
            return None
        else:
            store_admin_session(refreshed, previous=user)
            user = admin_session_from_state()
    return user


def admin_display_name(user: Mapping[str, Any]) -> str:
    display = str(user.get("display_name") or "").strip()
    email = str(user.get("email") or "").strip()
    return display or email or "관리자"


def admin_email(user: Mapping[str, Any] | None) -> str | None:
    if not user:
        return None
    email = str(user.get("email") or "").strip()
    return email or None


def admin_error_message() -> str | None:
    raw = st.session_state.get(_ADMIN_ERROR_KEY)
    if isinstance(raw, str) and raw.strip():
        return raw
    return None


__all__ = [
    "store_admin_session",
    "clear_admin_session",
    "admin_session_from_state",
    "ensure_active_admin_session",
    "admin_display_name",
    "admin_email",
    "admin_error_message",
]
